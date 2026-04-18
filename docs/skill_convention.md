# Skill Documentation Guideline (Anthropic Skills Convention)

This guideline helps you create **Skills** for Claude following the [Anthropic Skills repository](https://github.com/anthropics/skills) conventions.  
Skills are folders that teach Claude how to perform specialized tasks consistently.

## 1. Skill Folder Structure

A minimal skill consists of:

```
my-skill/
├── SKILL.md              # Required: instructions + frontmatter
├── REFERENCE.md          # Optional: advanced details, API references
├── FORMS.md              # Optional: form‑specific logic (PDF skill pattern)
├── scripts/              # Optional: Python, bash, or JS helpers
│   ├── check_*.py
│   └── fill_*.py
└── assets/               # Optional: images, templates, data files
```

**Rules:**
- Every skill **must** have a `SKILL.md` at the root.
- Additional `.md` files (e.g., `REFERENCE.md`, `FORMS.md`) are referenced from `SKILL.md` when the main guide becomes too long.
- Scripts live in a `scripts/` subfolder and are executed by Claude when needed.
- No extra configuration files – the skill is self‑contained.

---

## 2. SKILL.md Format

`SKILL.md` uses **YAML frontmatter** followed by **Markdown instructions**.

### 2.1 Frontmatter (Required)

```yaml
---
name: skill-name
description: A clear, comprehensive description of what this skill does and when Claude should use it.
license: Optional – e.g., "Proprietary", "MIT", "Apache-2.0"
---
```

- **`name`**: lowercase, use hyphens for spaces (e.g., `pdf-processing`, `brand-guidelines`).
- **`description`**: Critical for Claude to decide when to activate the skill. Include trigger keywords (e.g., "Use this skill whenever the user wants to do anything with PDF files").
- **`license`**: Optional but recommended if you redistribute the skill.

### 2.2 Body (Markdown)

The body contains the instructions Claude will follow. Structure it for clarity:

```markdown
# Skill Title (human readable)

## Overview
Brief summary of what the skill accomplishes.

## Quick Start
Minimal code or command example to get started.

## Detailed Instructions
- Step‑by‑step workflows
- Decision trees (e.g., "If X, go to REFERENCE.md; if Y, use scripts/...")
- Important constraints or gotchas

## Examples
Concrete usage examples.

## Guidelines
- Do’s and don’ts
- Error handling patterns

## Next Steps
Links to additional files (REFERENCE.md, FORMS.md, scripts) when needed.
```

**Key conventions from Anthropic’s skills:**
- **Explicit activation**: The description should contain clear triggers (e.g., "If the user mentions a .pdf file or asks to produce one, use this skill").
- **Progressive disclosure**: Keep `SKILL.md` focused on the 80% use case. Move advanced details, API references, or large tables to `REFERENCE.md`.
- **Script‑first approach**: When a task is complex (e.g., filling PDF forms), provide executable scripts in `scripts/` and instruct Claude to run them rather than writing code from scratch.
- **Validation steps**: Include validation commands (e.g., `python scripts/check_*.py`) before performing destructive actions.

---

## 3. Supporting Files

### 3.1 REFERENCE.md
Used for:
- Advanced library documentation (e.g., pypdfium2, pdf‑lib)
- Detailed API parameters
- Alternative methods
- Performance tuning

**Pattern:** The main `SKILL.md` says *“For advanced features, see REFERENCE.md”*.

### 3.2 FORMS.md (or similar domain‑specific files)
When a skill has a specialised sub‑workflow (e.g., filling PDF forms), extract that into its own file.  
The main skill instructs: *“If you need to fill out a PDF form, follow the instructions in FORMS.md”*.

### 3.3 Scripts (`scripts/`)
- Must be runnable from the skill’s root directory.
- Include shebangs and dependency hints (e.g., `# Requires: pip install pypdf`).
- Use descriptive names: `check_fillable_fields.py`, `extract_form_structure.py`.
- Scripts should print clear error messages so Claude can correct inputs.

**Example snippet from PDF skill:**

```python
# scripts/check_fillable_fields.py
import sys
from pypdf import PdfReader

def main():
    if len(sys.argv) != 2:
        print("Usage: python check_fillable_fields.py <pdf_file>")
        sys.exit(1)
    reader = PdfReader(sys.argv[1])
    if reader.get_form_fields():
        print("FILLABLE")
    else:
        print("NON_FILLABLE")

if __name__ == "__main__":
    main()
```

---

## 4. Writing Effective Descriptions

The **description** field is the single most important element. It must:

- **Unambiguously describe the domain** (e.g., "PDF manipulation – extract text, merge, split, fill forms").
- **List file extensions** that trigger the skill (e.g., ".pdf", ".docx").
- **Include action verbs** that users might say: “extract tables”, “rotate pages”, “add watermark”.
- **Avoid generic phrases** like “helps with documents” – be specific.

**Good example:**
```yaml
description: Use this skill whenever the user wants to do anything with PDF files. This includes reading or extracting text/tables from PDFs, merging multiple PDFs, splitting pages, rotating, adding watermarks, filling forms, encrypting/decrypting, and OCR on scanned PDFs. If the user mentions a .pdf file or asks to produce one, use this skill.
```

---

## 5. Content Guidelines for LLM Instructions

- **Be prescriptive, not descriptive** – tell Claude *exactly* which commands to run.
- **Prefer scripts over inline code** – for reproducibility and to avoid hallucinated APIs.
- **Include validation loops** – e.g., “After generating fields.json, run `check_bounding_boxes.py` and fix any errors before proceeding.”
- **State coordinate systems clearly** – “PDF coordinates (y=0 bottom)” vs “image coordinates (y=0 top)”.
- **Warn about common pitfalls** – e.g., “Never use Unicode subscripts in ReportLab – they render as black boxes.”
- **Use conditionals** – “If the PDF has fillable fields, go to section A; otherwise go to section B.”

---

## 6. Example Minimal Skill

**Folder:** `greeting-skill/`

**SKILL.md**
```yaml
---
name: greeting-generator
description: Creates personalized greeting messages in text or PDF format. Use when the user asks for a birthday card, welcome note, or any greeting text.
---

# Greeting Generator

## Overview
This skill produces friendly greetings with optional PDF output.

## Quick Start
To generate a plain text greeting:
```python
from scripts.make_greeting import create_text
print(create_text("Alice", "birthday"))
```

## Instructions
1. Ask the user for:
   - Recipient name
   - Occasion (birthday, welcome, thank you)
   - Output format (text or PDF)
2. Run the appropriate script from `scripts/`.

## Example
User: "Make a birthday greeting for John as PDF"
→ Run `python scripts/generate_pdf_greeting.py --name John --occasion birthday`

## Scripts
- `scripts/make_greeting.py` – returns text
- `scripts/generate_pdf_greeting.py` – creates PDF using reportlab
```

**scripts/make_greeting.py**
```python
def create_text(name, occasion):
    return f"Happy {occasion}, {name}!"
```

---

## 7. Checklist for a Compliant Skill

- [ ] Folder contains `SKILL.md` with valid YAML frontmatter (`name`, `description`).
- [ ] `description` is detailed and includes trigger conditions.
- [ ] Main instructions are concise; advanced info moved to `REFERENCE.md` if needed.
- [ ] Any external dependencies are mentioned (e.g., “Requires pypdf, pdfplumber”).
- [ ] Scripts are placed in `scripts/` and are executable.
- [ ] Validation steps are included where data is generated.
- [ ] Examples show realistic user queries and the corresponding Claude action.

---

## 8. References

- [Anthropic Skills Repository](https://github.com/anthropics/skills)
- [Agent Skills Specification](https://agentskills.io)
- Example skills to study: `skills/pdf` (complex), `skills/pptx` (document), `skills/theme-factory` (creative).

By following this guideline, you will create skills that integrate seamlessly with Claude’s runtime, are easy to maintain, and reliably perform the intended tasks.