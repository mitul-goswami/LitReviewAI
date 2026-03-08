"""
Writer Agent - Generates full literature review in Markdown and LaTeX
"""
import asyncio
import logging
from typing import Dict, List
from utils.groq_client import groq_chat

logger = logging.getLogger(__name__)


def build_citation_key(paper: Dict) -> str:
    """Generate a BibTeX citation key."""
    authors = paper.get("authors", [])
    first_author = authors[0].split()[-1] if authors else "Unknown"
    year = paper.get("year", 2020)
    title_words = (paper.get("title") or "").split()
    title_word = title_words[0].lower() if title_words else "paper"
    return f"{first_author.lower()}{year}{title_word}"


def generate_bibtex(papers: List[Dict]) -> str:
    """Generate BibTeX entries for all papers."""
    entries = []
    for paper in papers:
        key = build_citation_key(paper)
        authors = paper.get("authors", ["Unknown"])
        author_str = " and ".join(authors)
        title = paper.get("title", "Unknown Title").replace("{", "").replace("}", "")
        year = paper.get("year", 2020)
        venue = paper.get("venue", "")
        
        # Determine entry type
        entry_type = "article"
        if any(w in venue.lower() for w in ["proceedings", "conference", "workshop", "symposium", "iclr", "neurips", "icml", "cvpr", "emnlp", "acl"]):
            entry_type = "inproceedings"
        
        external_ids = paper.get("externalIds") or {}
        doi = external_ids.get("DOI", "")
        arxiv = external_ids.get("ArXiv", "")
        
        entry = f"@{entry_type}{{{key},\n"
        entry += f"  author = {{{author_str}}},\n"
        entry += f"  title = {{{{{title}}}}},\n"
        entry += f"  year = {{{year}}},\n"
        if entry_type == "inproceedings":
            entry += f"  booktitle = {{{venue}}},\n"
        else:
            entry += f"  journal = {{{venue}}},\n"
        if doi:
            entry += f"  doi = {{{doi}}},\n"
        if arxiv:
            entry += f"  eprint = {{{arxiv}}},\n  archivePrefix = {{arXiv}},\n"
        entry += "}"
        entries.append(entry)
    return "\n\n".join(entries)


async def generate_markdown_review(
    topic: str,
    papers: List[Dict],
    analysis: Dict,
) -> str:
    """Generate the full literature review in Markdown."""
    
    themes = analysis.get("themes", {})
    gaps = analysis.get("gaps", {})
    comparison = analysis.get("comparison", {})
    papers_text = analysis.get("papers_text_for_writer", "")

    # Build citation reference
    citation_map = {}
    for i, p in enumerate(papers):
        key = build_citation_key(p)
        citation_map[i + 1] = {"key": key, "title": p.get("title"), "year": p.get("year"), "authors": p.get("authors", [])}

    ref_block = "\n".join([
        f"[{i}] {', '.join(info['authors'][:3])}{'et al.' if len(info['authors']) > 3 else ''} ({info['year']}). {info['title']}."
        for i, info in citation_map.items()
    ])

    # Generate abstract + intro
    intro_section = await groq_chat(
        system_prompt="""You are a senior academic researcher writing a publishable literature review paper.
Write in formal academic style. Be thorough, precise, and insightful.
Use inline citations like [1], [2], [1,3] etc.""",
        user_prompt=f"""Write an Abstract and Introduction for a literature review on: "{topic}"

Papers covered (indices for citation):
{ref_block}

Research themes identified:
{themes}

Write:
1. **Abstract** (150-200 words): Overview of topic, scope, number of papers reviewed, key findings
2. **1. Introduction** (400-500 words): Background, motivation, why this review matters, scope and structure

Use academic writing. Cite relevant papers with [number] format.""",
        max_tokens=1500,
    )

    # Generate background section
    background_section = await groq_chat(
        system_prompt="You are a senior academic researcher writing a publishable literature review. Use formal academic style and inline citations [N].",
        user_prompt=f"""Topic: "{topic}"

Papers:
{papers_text[:3000]}

Write **2. Background and Preliminaries** (350-450 words):
- Fundamental concepts required to understand this research area
- Historical context and key milestones
- Cite specific papers where appropriate [N]""",
        max_tokens=1200,
    )

    # Generate thematic sections
    theme_list = themes.get("themes", [])
    thematic_content = []
    for i, theme in enumerate(theme_list[:5]):  # max 5 themes
        section_num = i + 3
        theme_name = theme.get("name", f"Theme {i+1}")
        theme_desc = theme.get("description", "")
        paper_indices = theme.get("paper_indices", [])
        key_finding = theme.get("key_finding", "")
        
        # Get papers in this theme
        theme_papers_text = "\n".join([
            papers_text.split("---")[j-1] if j-1 < len(papers_text.split("---")) else ""
            for j in paper_indices[:5]
        ])
        
        theme_section = await groq_chat(
            system_prompt="You are writing a literature review. Use formal academic style and cite papers as [N].",
            user_prompt=f"""Write section {section_num} for a literature review on "{topic}":

Section title: "{theme_name}"
Description: {theme_desc}
Key finding: {key_finding}
Relevant paper indices: {paper_indices}

Papers:
{papers_text[:2500]}

Write a thorough academic section (300-400 words) covering:
- Main approaches and contributions in this theme
- Comparison of different methods
- Key results and insights
- Cite papers as [N] inline

Start with: **{section_num}. {theme_name}**""",
            max_tokens=1000,
        )
        thematic_content.append(theme_section)
        await asyncio.sleep(0.3)

    # Generate comparison/discussion section
    comparison_section = await groq_chat(
        system_prompt="You are writing a literature review. Use formal academic style.",
        user_prompt=f"""Topic: "{topic}"

Comparison data:
{comparison}

Research gaps:
{gaps}

Write **{len(theme_list)+3}. Comparative Analysis and Discussion** (400-500 words):
- Systematic comparison of methodologies
- Key similarities and differences
- What the field has learned
- Contradictions or debates in the literature
- Cite papers as [N] inline

Also include a short subsection on **Research Gaps** listing the main open problems.""",
        max_tokens=1200,
    )

    # Generate conclusion
    conclusion_section = await groq_chat(
        system_prompt="You are writing a literature review conclusion. Be concise and forward-looking.",
        user_prompt=f"""Topic: "{topic}"
Gaps: {gaps.get('gaps', [])}
Future directions: {gaps.get('future_directions', [])}
Consensus: {gaps.get('consensus', [])}

Write **{len(theme_list)+4}. Conclusion and Future Directions** (300-400 words):
- Summary of key findings across the literature
- State of the field assessment
- Most promising future research directions
- Closing remarks on the field's trajectory""",
        max_tokens=800,
    )

    # Assemble full markdown
    dom_methods = ", ".join(comparison.get("dominant_methods", []))
    common_data = ", ".join(themes.get("common_datasets", []))
    maturity = comparison.get("field_maturity", "developing")
    
    full_review = f"""# A Survey of {topic}: Methods, Advances, and Future Directions

*Automatically generated literature review covering {len(papers)} papers*

---

{intro_section}

---

{background_section}

---

{"---".join(thematic_content)}

---

{comparison_section}

---

{conclusion_section}

---

## References

{ref_block}

---

*Generated by Autonomous Literature Review Generator | Papers reviewed: {len(papers)} | Field maturity: {maturity}*
"""
    return full_review


def markdown_to_latex(topic: str, markdown_text: str, papers: List[Dict]) -> str:
    """Convert the markdown review to a LaTeX document."""
    bibtex = generate_bibtex(papers)
    
    # Clean and escape special LaTeX chars in topic
    safe_topic = topic.replace("&", "\\&").replace("%", "\\%").replace("_", "\\_").replace("#", "\\#")
    
    # Convert markdown to LaTeX (basic)
    import re
    
    latex_body = markdown_text
    
    # Remove the header line (# title)
    latex_body = re.sub(r'^# .+\n', '', latex_body, flags=re.MULTILINE)
    # Remove italics metadata line
    latex_body = re.sub(r'^\*Automatically.+\*\n', '', latex_body, flags=re.MULTILINE)
    # Remove horizontal rules
    latex_body = re.sub(r'^---+$', '', latex_body, flags=re.MULTILINE)
    # Remove footer line
    latex_body = re.sub(r'^\*Generated by.+\*$', '', latex_body, flags=re.MULTILINE)
    
    # Convert ## headers to \section
    latex_body = re.sub(r'^## (.+)$', r'\\section{\1}', latex_body, flags=re.MULTILINE)
    # Convert ### headers to \subsection
    latex_body = re.sub(r'^### (.+)$', r'\\subsection{\1}', latex_body, flags=re.MULTILINE)
    # Convert **bold** to \textbf
    latex_body = re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', latex_body)
    # Convert *italic* to \textit
    latex_body = re.sub(r'\*(.+?)\*', r'\\textit{\1}', latex_body)
    
    # Convert References section
    ref_section_match = re.search(r'## References\n(.*?)$', latex_body, re.DOTALL)
    if ref_section_match:
        latex_body = latex_body[:ref_section_match.start()]
    
    # Escape remaining special chars (but not already escaped)
    latex_body = re.sub(r'(?<!\\)&', r'\\&', latex_body)
    latex_body = re.sub(r'(?<!\\)%', r'\\%', latex_body)
    
    # Extract abstract
    abstract_match = re.search(r'\\textbf\{Abstract\}(.+?)\\section', latex_body, re.DOTALL)
    if not abstract_match:
        abstract_match = re.search(r'Abstract\n(.+?)(\n\n|\Z)', latex_body, re.DOTALL)
    abstract_text = abstract_match.group(1).strip() if abstract_match else f"A comprehensive literature review on {safe_topic}."
    abstract_text = abstract_text[:800]
    
    # Get first author from papers for author field
    all_authors = set()
    for p in papers[:3]:
        for a in (p.get("authors") or [])[:1]:
            all_authors.add(a)
    
    latex_doc = r"""\documentclass[12pt,a4paper]{article}

% Packages
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{hyperref}
\usepackage{natbib}
\usepackage{geometry}
\usepackage{setspace}
\usepackage{parskip}
\usepackage{microtype}
\usepackage{xcolor}

% Page geometry
\geometry{margin=1in}
\doublespacing

% Hyperref setup
\hypersetup{
    colorlinks=true,
    linkcolor=blue!70!black,
    citecolor=green!50!black,
    urlcolor=blue!70!black,
}

% Title
\title{\textbf{A Survey of """ + safe_topic + r"""}: \\
       Methods, Advances, and Future Directions}

\author{Autonomous Literature Review Generator \\
        \small{AI-Assisted Research Synthesis}}

\date{\today}

\begin{document}

\maketitle

\begin{abstract}
""" + abstract_text + r"""
\end{abstract}

\tableofcontents
\newpage

""" + latex_body + r"""

\newpage
\section*{References}
\bibliographystyle{plainnat}

% BibTeX entries (save as references.bib and compile with bibtex)
% \bibliography{references}

% Inline bibliography
\begin{thebibliography}{99}
"""
    
    # Add inline bibliography
    for i, paper in enumerate(papers):
        key = build_citation_key(paper)
        authors = paper.get("authors", ["Unknown"])
        author_str = ", ".join(authors[:4])
        if len(authors) > 4:
            author_str += " et al."
        title = paper.get("title", "Unknown Title")
        year = paper.get("year", "N/A")
        venue = paper.get("venue", "")
        url = paper.get("url", "")
        
        bib_entry = f"\\bibitem{{{key}}}\n{author_str}.\n\\textit{{{title}}}.\n{venue}, {year}."
        if url:
            bib_entry += f" \\url{{{url}}}"
        latex_doc += bib_entry + "\n\n"
    
    latex_doc += r"""\end{thebibliography}

\end{document}"""
    
    return latex_doc


async def run_writer_agent(
    topic: str,
    papers: List[Dict],
    analysis: Dict,
    job_id: str,
    state_manager,
) -> tuple:
    """
    Writer Agent: generates full literature review in Markdown + LaTeX.
    """
    state_manager.update(job_id, current_agent="✍️ Writer Agent", progress=75)
    state_manager.add_log(job_id, "Generating literature review text...")

    # Generate Markdown
    state_manager.add_log(job_id, "Writing introduction and background...")
    markdown = await generate_markdown_review(topic, papers, analysis)
    state_manager.update(job_id, progress=90)

    # Convert to LaTeX
    state_manager.add_log(job_id, "Converting to LaTeX format...")
    latex = markdown_to_latex(topic, markdown, papers)
    state_manager.update(job_id, progress=95)

    state_manager.add_log(job_id, "Literature review generation complete! 🎉", "success")
    
    return markdown, latex
