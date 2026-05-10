from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.browser_state import cache_file


def snapshot_target(target: Any, config: dict[str, Any], session_id: str, label: str = "dom") -> dict[str, Any]:
    options = snapshot_options(config)
    snapshot = target.evaluate(SNAPSHOT_SCRIPT, options)
    if not isinstance(snapshot, dict):
        snapshot = {"url": "", "title": "", "interactive_elements": {}, "page_structure": {}}
    path = cache_file(config, session_id, label)
    write_snapshot(path, snapshot)
    snapshot["snapshot_path"] = str(path)
    return snapshot


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")


def snapshot_options(config: dict[str, Any]) -> dict[str, Any]:
    dom_config = config.get("dom_snapshot")
    if not isinstance(dom_config, dict):
        dom_config = {}
    return {
        "maxElementsPerType": bounded_int(dom_config.get("max_elements_per_type"), 50, 1, 500),
        "includeHiddenInputs": bool(dom_config.get("include_hidden_inputs", True)),
        "includeAccessibilityTree": bool(dom_config.get("include_accessibility_tree", True)),
        "maxTextPerElement": bounded_int(dom_config.get("max_text_per_element"), 200, 20, 2000),
    }


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


SNAPSHOT_SCRIPT = """
(options) => {
  const limit = Number(options.maxElementsPerType || 50);
  const textLimit = Number(options.maxTextPerElement || 200);
  const includeHiddenInputs = Boolean(options.includeHiddenInputs);
  const includeAccessibilityTree = Boolean(options.includeAccessibilityTree);

  const trimText = (value) => {
    const text = String(value || "").replaceAll("\\n", " ").replaceAll("\\t", " ").trim();
    return text.length > textLimit ? text.slice(0, textLimit) : text;
  };
  let refCounter = 0;
  const refs = {};
  const elementRefs = new WeakMap();
  const refFor = (element) => {
    if (!elementRefs.has(element)) {
      refCounter += 1;
      elementRefs.set(element, "e" + refCounter);
    }
    return elementRefs.get(element);
  };

  const isVisible = (element) => {
    if (!element || !element.getBoundingClientRect) {
      return false;
    }
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
  };

  const rectFor = (element) => {
    if (!element || !element.getBoundingClientRect) {
      return null;
    }
    const rect = element.getBoundingClientRect();
    return {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height)
    };
  };

  const cssPath = (element) => {
    if (!element || !element.tagName) {
      return "";
    }
    if (element.id) {
      return "#" + CSS.escape(element.id);
    }
    const parts = [];
    let current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.body) {
      let name = current.tagName.toLowerCase();
      if (current.classList && current.classList.length > 0) {
        const usable = Array.from(current.classList).filter((item) => item && item.length < 60).slice(0, 2);
        if (usable.length > 0) {
          name = name + "." + usable.map((item) => CSS.escape(item)).join(".");
        }
      }
      const parent = current.parentElement;
      if (parent) {
        const sameTag = Array.from(parent.children).filter((child) => child.tagName === current.tagName);
        if (sameTag.length > 1) {
          name = name + ":nth-of-type(" + (sameTag.indexOf(current) + 1) + ")";
        }
      }
      parts.unshift(name);
      current = parent;
      if (parts.length >= 5) {
        break;
      }
    }
    return parts.join(" > ");
  };

  const labelFor = (element) => {
    if (!element) {
      return "";
    }
    const aria = element.getAttribute("aria-label");
    if (aria) {
      return trimText(aria);
    }
    const labelledBy = element.getAttribute("aria-labelledby");
    if (labelledBy) {
      const labelElement = document.getElementById(labelledBy);
      if (labelElement) {
        return trimText(labelElement.innerText || labelElement.textContent);
      }
    }
    if (element.id) {
      const label = document.querySelector("label[for='" + CSS.escape(element.id) + "']");
      if (label) {
        return trimText(label.innerText || label.textContent);
      }
    }
    const parentLabel = element.closest("label");
    if (parentLabel) {
      return trimText(parentLabel.innerText || parentLabel.textContent);
    }
    return "";
  };

  const elementSummary = (element) => {
    const ref = refFor(element);
    const summary = {
      ref,
      text: trimText(element.innerText || element.textContent || element.value || ""),
      label: labelFor(element),
      selector: cssPath(element),
      visible: isVisible(element),
      enabled: !Boolean(element.disabled),
      bounding_box: rectFor(element),
      role: element.getAttribute("role") || "",
      aria_label: element.getAttribute("aria-label") || ""
    };
    refs[ref] = summary;
    return summary;
  };

  const collect = (selector, mapper) => {
    const result = [];
    for (const element of Array.from(document.querySelectorAll(selector))) {
      if (result.length >= limit) {
        break;
      }
      const mapped = mapper(element);
      if (mapped) {
        result.push(mapped);
      }
    }
    return result;
  };

  const buttons = collect("button, input[type='button'], input[type='submit'], input[type='reset'], [role='button']", (element) => ({
    ...elementSummary(element),
    type: element.getAttribute("type") || element.tagName.toLowerCase()
  }));

  const inputs = collect("input", (element) => {
    const type = element.getAttribute("type") || "text";
    if (type === "hidden" && !includeHiddenInputs) {
      return null;
    }
    return {
      ...elementSummary(element),
      type,
      name: element.getAttribute("name") || "",
      placeholder: element.getAttribute("placeholder") || "",
      value: type === "password" ? "" : String(element.value || "").slice(0, textLimit),
      required: Boolean(element.required),
      autocomplete: element.getAttribute("autocomplete") || ""
    };
  });

  const editableElements = collect("[contenteditable='true'], [contenteditable='plaintext-only'], [role='textbox']", (element) => ({
    ...elementSummary(element),
    tag: element.tagName.toLowerCase(),
    contenteditable: element.getAttribute("contenteditable") || "",
    current_value: trimText(element.innerText || element.textContent || ""),
    multiline: element.getAttribute("aria-multiline") || ""
  }));

  const comboboxes = collect("[role='combobox'], input[aria-autocomplete], input[list], [aria-haspopup='listbox'], [aria-expanded]", (element) => ({
    ...elementSummary(element),
    tag: element.tagName.toLowerCase(),
    type: element.getAttribute("type") || "",
    name: element.getAttribute("name") || "",
    placeholder: element.getAttribute("placeholder") || "",
    value: element.tagName.toLowerCase() === "input" ? String(element.value || "").slice(0, textLimit) : trimText(element.innerText || element.textContent || ""),
    expanded: element.getAttribute("aria-expanded") || "",
    controls: element.getAttribute("aria-controls") || "",
    autocomplete: element.getAttribute("aria-autocomplete") || "",
    owns: element.getAttribute("aria-owns") || ""
  }));

  const selects = collect("select", (element) => ({
    ...elementSummary(element),
    name: element.getAttribute("name") || "",
    current_value: element.value || "",
    options: Array.from(element.options || []).slice(0, limit).map((option) => ({
      value: option.value,
      label: trimText(option.label || option.textContent),
      selected: Boolean(option.selected)
    }))
  }));

  const listboxes = collect("[role='listbox'], [role='menu'], datalist, ul[role='listbox'], div[role='listbox']", (element) => ({
    ...elementSummary(element),
    tag: element.tagName.toLowerCase(),
    expanded: element.getAttribute("aria-expanded") || "",
    option_count: element.querySelectorAll("[role='option'], [role='menuitem'], option, li").length
  }));

  const optionItems = collect("[role='option'], [role='menuitem'], option, datalist option", (element) => ({
    ...elementSummary(element),
    tag: element.tagName.toLowerCase(),
    value: element.getAttribute("value") || "",
    selected: Boolean(element.selected || element.getAttribute("aria-selected") === "true"),
    disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true")
  }));

  const links = collect("a[href]", (element) => ({
    ...elementSummary(element),
    href: element.href || ""
  }));

  const checkboxes = collect("input[type='checkbox'], input[type='radio'], [role='checkbox'], [role='radio']", (element) => ({
    ...elementSummary(element),
    type: element.getAttribute("type") || element.getAttribute("role") || "",
    name: element.getAttribute("name") || "",
    checked: Boolean(element.checked || element.getAttribute("aria-checked") === "true")
  }));

  const textareas = collect("textarea", (element) => ({
    ...elementSummary(element),
    name: element.getAttribute("name") || "",
    placeholder: element.getAttribute("placeholder") || "",
    current_value: String(element.value || "").slice(0, textLimit),
    required: Boolean(element.required)
  }));

  const iframes = collect("iframe", (element) => ({
    ...elementSummary(element),
    src: element.src || "",
    name: element.getAttribute("name") || "",
    accessible: (() => {
      try {
        return Boolean(element.contentDocument);
      } catch (error) {
        return false;
      }
    })()
  }));

  const headings = collect("h1, h2, h3, h4, h5, h6, [role='heading']", (element) => ({
    level: Number(element.tagName && element.tagName.length === 2 ? element.tagName.slice(1) : element.getAttribute("aria-level") || 0),
    text: trimText(element.innerText || element.textContent),
    selector: cssPath(element),
    visible: isVisible(element)
  }));

  const forms = collect("form", (element) => ({
    name: element.getAttribute("name") || element.getAttribute("id") || "",
    selector: cssPath(element),
    visible: isVisible(element),
    fields: Array.from(element.querySelectorAll("input, select, textarea, button")).slice(0, limit).map((field) => ({
      selector: cssPath(field),
      tag: field.tagName.toLowerCase(),
      type: field.getAttribute("type") || "",
      name: field.getAttribute("name") || "",
      label: labelFor(field),
      placeholder: field.getAttribute("placeholder") || "",
      required: Boolean(field.required)
    }))
  }));

  const alerts = collect("[role='alert'], [role='status'], [aria-live]", (element) => ({
    text: trimText(element.innerText || element.textContent),
    selector: cssPath(element),
    visible: isVisible(element),
    role: element.getAttribute("role") || "",
    live: element.getAttribute("aria-live") || ""
  }));

  const modals = collect("[role='dialog'], [aria-modal='true'], dialog", (element) => ({
    text: trimText(element.innerText || element.textContent),
    selector: cssPath(element),
    visible: isVisible(element),
    role: element.getAttribute("role") || "",
    modal: element.getAttribute("aria-modal") || ""
  }));

  const loadingIndicators = collect("[aria-busy='true'], [role='progressbar'], progress", (element) => ({
    text: trimText(element.innerText || element.textContent),
    selector: cssPath(element),
    visible: isVisible(element),
    role: element.getAttribute("role") || ""
  }));

  const accessibility = includeAccessibilityTree ? collect("[role], [aria-label], [aria-labelledby]", (element) => ({
    selector: cssPath(element),
    role: element.getAttribute("role") || "",
    label: labelFor(element),
    text: trimText(element.innerText || element.textContent),
    visible: isVisible(element)
  })) : [];

  const main = document.querySelector("main, [role='main']") || document.body;
  const mainContent = trimText((main && (main.innerText || main.textContent)) || "");
  const schemaTypes = [];
  for (const item of Array.from(document.querySelectorAll("script[type='application/ld+json']"))) {
    try {
      const parsed = JSON.parse(item.textContent || "{}");
      const values = Array.isArray(parsed) ? parsed : [parsed];
      for (const value of values) {
        if (value && typeof value === "object" && typeof value["@type"] === "string" && schemaTypes.length < limit) {
          schemaTypes.push(value["@type"]);
        }
      }
    } catch (error) {
    }
  }

  return {
    url: window.location.href,
    title: document.title || "",
    timestamp: new Date().toISOString(),
    interactive_elements: {
      buttons,
      inputs,
      editable_elements: editableElements,
      comboboxes,
      selects,
      listboxes,
      options: optionItems,
      links,
      checkboxes,
      textareas,
      iframes
    },
    page_structure: {
      headings,
      forms,
      main_content: mainContent,
      alerts,
      modals,
      loading_indicators: loadingIndicators
    },
    accessibility_tree: accessibility,
    schema_types: schemaTypes,
    refs,
    counts: {
      buttons: buttons.length,
      inputs: inputs.length,
      editable_elements: editableElements.length,
      comboboxes: comboboxes.length,
      selects: selects.length,
      listboxes: listboxes.length,
      options: optionItems.length,
      links: links.length,
      checkboxes: checkboxes.length,
      textareas: textareas.length,
      iframes: iframes.length,
      forms: forms.length
    }
  };
}
"""
