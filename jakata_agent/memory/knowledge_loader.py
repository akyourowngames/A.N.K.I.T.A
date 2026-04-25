from __future__ import annotations

from pathlib import Path


class KnowledgeLoader:
    def __init__(self, knowledge_dir: Path, chunk_size: int = 700, overlap: int = 100) -> None:
        self.knowledge_dir = knowledge_dir
        self.chunk_size = chunk_size
        self.overlap = overlap

    def load_chunks(self) -> list[str]:
        chunks: list[str] = []
        for path in sorted(self.knowledge_dir.glob("*.txt")):
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            for unit in self._split_units(text):
                chunks.extend(self._chunk_text(unit))
        return chunks

    @staticmethod
    def _split_units(text: str) -> list[str]:
        paragraphs = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
        units: list[str] = []
        for paragraph in paragraphs or [text.strip()]:
            lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
            if len(lines) > 1:
                units.extend(lines)
            else:
                units.append(paragraph)
        return units

    def _chunk_text(self, text: str) -> list[str]:
        if len(text) <= self.chunk_size:
            return [text]

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunks.append(text[start:end].strip())
            if end >= len(text):
                break
            start = max(end - self.overlap, start + 1)
        return [chunk for chunk in chunks if chunk]

