(function ankitaBrowserContentScript() {
  if (window.__ankitaBrowserContentScriptLoaded) {
    return;
  }
  window.__ankitaBrowserContentScriptLoaded = true;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function isVisible(element) {
    if (!element || !(element instanceof Element)) {
      return false;
    }
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function textValue(element) {
    if (!element) {
      return "";
    }
    if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
      return normalizeText(element.value || element.getAttribute("value"));
    }
    return normalizeText(
      element.innerText ||
      element.textContent ||
      element.getAttribute("aria-label") ||
      element.getAttribute("title") ||
      ""
    );
  }

  function firstVisible(elements) {
    return elements.find((element) => isVisible(element)) || elements[0] || null;
  }

  function xpathQuery(xpath) {
    const result = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
    const nodes = [];
    for (let index = 0; index < result.snapshotLength; index += 1) {
      nodes.push(result.snapshotItem(index));
    }
    return nodes;
  }

  function findByText(text) {
    const wanted = normalizeText(text).toLowerCase();
    if (!wanted) {
      return null;
    }
    const candidates = Array.from(
      document.querySelectorAll("button, a, label, input, textarea, select, option, span, div, p, h1, h2, h3, h4, h5, h6")
    );
    const exact = candidates.filter((element) => textValue(element).toLowerCase() === wanted);
    if (exact.length) {
      return firstVisible(exact);
    }
    const partial = candidates.filter((element) => textValue(element).toLowerCase().includes(wanted));
    return firstVisible(partial);
  }

  function findByPlaceholder(value) {
    const wanted = normalizeText(value).toLowerCase();
    const candidates = Array.from(document.querySelectorAll("input[placeholder], textarea[placeholder]"));
    const matches = candidates.filter(
      (element) => normalizeText(element.getAttribute("placeholder")).toLowerCase() === wanted
    );
    if (matches.length) {
      return firstVisible(matches);
    }
    return firstVisible(
      candidates.filter((element) =>
        normalizeText(element.getAttribute("placeholder")).toLowerCase().includes(wanted)
      )
    );
  }

  function findByAriaLabel(value) {
    const wanted = normalizeText(value).toLowerCase();
    const candidates = Array.from(document.querySelectorAll("[aria-label]"));
    const matches = candidates.filter(
      (element) => normalizeText(element.getAttribute("aria-label")).toLowerCase() === wanted
    );
    if (matches.length) {
      return firstVisible(matches);
    }
    return firstVisible(
      candidates.filter((element) =>
        normalizeText(element.getAttribute("aria-label")).toLowerCase().includes(wanted)
      )
    );
  }

  function findByLabel(labelText) {
    const wanted = normalizeText(labelText).toLowerCase();
    const labels = Array.from(document.querySelectorAll("label"));
    for (const label of labels) {
      const labelValue = normalizeText(label.innerText || label.textContent).toLowerCase();
      if (!labelValue || (labelValue !== wanted && !labelValue.includes(wanted))) {
        continue;
      }
      if (label.htmlFor) {
        const linked = document.getElementById(label.htmlFor);
        if (linked) {
          return linked;
        }
      }
      const nestedField = label.querySelector("input, textarea, select");
      if (nestedField) {
        return nestedField;
      }
      let sibling = label.nextElementSibling;
      while (sibling) {
        const field = sibling.matches("input, textarea, select")
          ? sibling
          : sibling.querySelector("input, textarea, select");
        if (field) {
          return field;
        }
        sibling = sibling.nextElementSibling;
      }
    }
    return null;
  }

  function selectorForRole(role) {
    switch (String(role || "").toLowerCase()) {
      case "button":
        return "button, [role='button'], input[type='button'], input[type='submit']";
      case "textbox":
        return "input:not([type='button']):not([type='submit']):not([type='checkbox']):not([type='radio']):not([type='hidden']):not([type='file']), textarea, [role='textbox']";
      case "link":
        return "a[href], [role='link']";
      case "checkbox":
        return "input[type='checkbox'], [role='checkbox']";
      case "radio":
        return "input[type='radio'], [role='radio']";
      case "combobox":
        return "select, [role='combobox']";
      default:
        return `[role='${CSS.escape(role)}']`;
    }
  }

  function findByRoleAndName(role, name) {
    const selector = selectorForRole(role);
    const wanted = normalizeText(name).toLowerCase();
    const candidates = Array.from(document.querySelectorAll(selector));
    const matches = candidates.filter((element) => {
      const descriptors = [
        textValue(element),
        normalizeText(element.getAttribute("aria-label")),
        normalizeText(element.getAttribute("title")),
        normalizeText(element.getAttribute("placeholder")),
        normalizeText(element.value),
      ];
      return descriptors.some((descriptor) => descriptor && descriptor.toLowerCase() === wanted);
    });
    if (matches.length) {
      return firstVisible(matches);
    }
    return firstVisible(
      candidates.filter((element) => {
        const descriptors = [
          textValue(element),
          normalizeText(element.getAttribute("aria-label")),
          normalizeText(element.getAttribute("title")),
          normalizeText(element.getAttribute("placeholder")),
          normalizeText(element.value),
        ];
        return descriptors.some((descriptor) => descriptor && descriptor.toLowerCase().includes(wanted));
      })
    );
  }

  function resolveTarget(target) {
    if (!target || typeof target !== "object") {
      return null;
    }
    if (target.css) {
      return firstVisible(Array.from(document.querySelectorAll(target.css)));
    }
    if (target.xpath) {
      return firstVisible(xpathQuery(target.xpath));
    }
    if (target.id) {
      return document.getElementById(target.id);
    }
    if (target.name) {
      return firstVisible(Array.from(document.getElementsByName(target.name)));
    }
    if (target.class_name) {
      return firstVisible(Array.from(document.getElementsByClassName(target.class_name)));
    }
    if (target.tag_name) {
      return firstVisible(Array.from(document.getElementsByTagName(target.tag_name)));
    }
    if (target.placeholder) {
      return findByPlaceholder(target.placeholder);
    }
    if (target.aria_label) {
      return findByAriaLabel(target.aria_label);
    }
    if (target.label) {
      return findByLabel(target.label);
    }
    if (target.role && target.name) {
      return findByRoleAndName(target.role, target.name);
    }
    if (target.text) {
      return findByText(target.text);
    }
    return null;
  }

  function setNativeValue(element, value) {
    const prototype = element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    if (descriptor && descriptor.set) {
      descriptor.set.call(element, value);
    } else {
      element.value = value;
    }
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function focusElement(element) {
    element.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
    element.focus({ preventScroll: true });
  }

  function clickElement(element) {
    focusElement(element);
    try {
      element.click();
    } catch (_error) {
      const rect = element.getBoundingClientRect();
      const options = {
        bubbles: true,
        cancelable: true,
        clientX: rect.left + rect.width / 2,
        clientY: rect.top + rect.height / 2,
      };
      element.dispatchEvent(new MouseEvent("mousedown", options));
      element.dispatchEvent(new MouseEvent("mouseup", options));
      element.dispatchEvent(new MouseEvent("click", options));
    }
  }

  async function waitForTarget(step) {
    const timeoutMs = Number(step.timeout_sec || 20) * 1000;
    const deadline = Date.now() + timeoutMs;
    const wantedText = normalizeText(step.text).toLowerCase();
    const condition = String(step.condition || "visible").toLowerCase();

    while (Date.now() < deadline) {
      if (step.target) {
        const element = resolveTarget(step.target);
        if (element) {
          if (condition === "presence" || isVisible(element)) {
            return element;
          }
        }
      } else if (wantedText && normalizeText(document.body.innerText).toLowerCase().includes(wantedText)) {
        return true;
      }
      await sleep(120);
    }

    throw new Error("wait_for condition timed out");
  }

  function buildSnapshot(maxItems = 10) {
    const limit = Math.max(1, Number(maxItems || 10));
    const headings = Array.from(document.querySelectorAll("h1,h2,h3"))
      .map((element) => normalizeText(element.innerText))
      .filter(Boolean)
      .slice(0, limit);

    const buttons = Array.from(document.querySelectorAll("button, [role='button'], input[type='button'], input[type='submit']"))
      .map((element) => textValue(element))
      .filter(Boolean)
      .slice(0, limit);

    const links = Array.from(document.querySelectorAll("a[href]"))
      .map((element) => ({
        text: normalizeText(element.innerText),
        href: element.href,
      }))
      .filter((entry) => entry.text || entry.href)
      .slice(0, limit);

    const fields = Array.from(document.querySelectorAll("input, textarea, select"))
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        type: element.type || null,
        name: element.name || null,
        id: element.id || null,
        placeholder: element.placeholder || null,
        aria_label: element.getAttribute("aria-label"),
      }))
      .slice(0, limit);

    return {
      url: window.location.href,
      title: document.title,
      headings,
      buttons,
      links,
      fields,
    };
  }

  async function runStep(step) {
    const type = String(step.type || "").toLowerCase();

    if (type === "wait_for") {
      await waitForTarget(step);
      return { ok: true };
    }

    if (type === "snapshot") {
      return { ok: true, snapshot: buildSnapshot(step.max_items || 10) };
    }

    if (type === "extract") {
      const mode = String(step.mode || "text").toLowerCase();
      const target = step.target ? resolveTarget(step.target) : document.body;
      if (!target) {
        throw new Error("extract target not found");
      }
      if (mode === "html") {
        return { ok: true, output: target.innerHTML };
      }
      if (mode === "attribute") {
        if (!step.attribute) {
          throw new Error("extract attribute mode requires attribute");
        }
        return { ok: true, output: target.getAttribute(step.attribute) };
      }
      if (mode === "value") {
        return { ok: true, output: target.value ?? null };
      }
      if (mode === "exists") {
        return { ok: true, output: true };
      }
      return { ok: true, output: textValue(target) || normalizeText(target.innerText || target.textContent) };
    }

    if (type === "scroll") {
      if (step.target) {
        const element = resolveTarget(step.target);
        if (!element) {
          throw new Error("scroll target not found");
        }
        element.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
      } else {
        window.scrollBy({ top: Number(step.amount || 800), left: 0, behavior: "smooth" });
      }
      return { ok: true };
    }

    if (type === "hover") {
      const element = resolveTarget(step.target);
      if (!element) {
        throw new Error("hover target not found");
      }
      focusElement(element);
      element.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      element.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
      return { ok: true };
    }

    if (type === "click") {
      const element = resolveTarget(step.target);
      if (!element) {
        throw new Error("click target not found");
      }
      clickElement(element);
      return { ok: true };
    }

    if (type === "fill") {
      const element = resolveTarget(step.target);
      if (!element) {
        throw new Error("fill target not found");
      }
      if (element.type === "file") {
        throw new Error("file inputs are not supported via extension fill");
      }
      focusElement(element);
      if (element.isContentEditable) {
        element.textContent = step.text || "";
        element.dispatchEvent(new Event("input", { bubbles: true }));
      } else {
        setNativeValue(element, step.text || "");
      }
      return { ok: true, value: step.text || "" };
    }

    if (type === "select") {
      const element = resolveTarget(step.target);
      if (!element) {
        throw new Error("select target not found");
      }
      if (!(element instanceof HTMLSelectElement)) {
        throw new Error("target is not a <select> element");
      }
      const wanted = normalizeText(step.value).toLowerCase();
      const option = Array.from(element.options).find(
        (candidate) =>
          normalizeText(candidate.value).toLowerCase() === wanted ||
          normalizeText(candidate.text).toLowerCase() === wanted
      );
      if (!option) {
        throw new Error(`select option not found: ${step.value}`);
      }
      element.value = option.value;
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
      return { ok: true, value: option.value };
    }

    if (type === "check" || type === "uncheck") {
      const element = resolveTarget(step.target);
      if (!element) {
        throw new Error(`${type} target not found`);
      }
      if (!(element instanceof HTMLInputElement) || element.type !== "checkbox") {
        throw new Error(`${type} target is not a checkbox`);
      }
      element.checked = type === "check";
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
      return { ok: true, value: element.checked };
    }

    if (type === "press") {
      const key = String(step.key || step.text || step.value || "").trim();
      if (!key) {
        throw new Error("press step requires key/text/value");
      }
      const element = step.target ? resolveTarget(step.target) : document.activeElement;
      if (!element) {
        throw new Error("press target not found");
      }
      focusElement(element);
      const dispatch = (eventType) =>
        element.dispatchEvent(
          new KeyboardEvent(eventType, {
            key,
            bubbles: true,
            cancelable: true,
          })
        );

      dispatch("keydown");
      dispatch("keypress");
      if (key === "Enter" && element.form && typeof element.form.requestSubmit === "function") {
        element.form.requestSubmit();
      }
      dispatch("keyup");
      return { ok: true, value: key };
    }

    if (type === "script") {
      throw new Error("arbitrary script execution is not enabled in the extension executor");
    }

    throw new Error(`unsupported_dom_step:${type}`);
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || !message.type) {
      sendResponse({ ok: false, error: "invalid_message" });
      return false;
    }

    if (message.type === "ankita_ping") {
      sendResponse({ ok: true });
      return false;
    }

    if (message.type === "ankita_snapshot") {
      Promise.resolve()
        .then(() => ({ ok: true, snapshot: buildSnapshot(message.maxItems || 10) }))
        .then(sendResponse)
        .catch((error) => sendResponse({ ok: false, error: String(error.message || error) }));
      return true;
    }

    if (message.type === "ankita_dom_step") {
      Promise.resolve()
        .then(() => runStep(message.step || {}))
        .then(sendResponse)
        .catch((error) => sendResponse({ ok: false, error: String(error.message || error) }));
      return true;
    }

    sendResponse({ ok: false, error: `unsupported_message:${message.type}` });
    return false;
  });
})();
