#!/usr/bin/env python3
r"""
Check cross-references in LaTeX files for validity.

Validates:
- \ref{label} references have corresponding \label{label}
- \pageref{label} references have corresponding \label{label}
- \hyperref[label]{text} references have corresponding \label{label}
- Cross-volume references (vol1 → vol2, etc.)

Usage:
    python check_refs.py vol1_experimentation/**/*.tex
    python check_refs.py --all  # Check all volumes
"""

import argparse
import re
import sys
from pathlib import Path
from collections import defaultdict
from typing import NamedTuple


def _strip_latex_comments(content: str) -> str:
    r"""Blank out LaTeX comments (an unescaped ``%`` to end-of-line), preserving line structure.

    A line starting with ``%`` becomes empty; ``code  % note`` keeps ``code  ``. ``\%`` (escaped) is
    NOT a comment. Newlines are preserved so line numbers (and multi-line bodies) are unaffected — so a
    commented-out ``\label``/``\ref`` no longer counts (guides-tooling#4 p11/p12).
    """
    out = []
    for line in content.split("\n"):
        cut = None
        for i, ch in enumerate(line):
            if ch == "%" and (i == 0 or line[i - 1] != "\\"):
                cut = i
                break
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


class RefIssue(NamedTuple):
    """A cross-reference issue found during validation."""
    file: str
    line: int
    ref_type: str
    label: str
    message: str


def extract_labels(content: str, filepath: str) -> dict[str, list[tuple[int, str]]]:
    r"""Extract all \label{...} definitions from LaTeX content.

    Returns dict mapping label name to list of (line_number, file) tuples.

    Also recognises macro-generated labels:
    - ``\moduleheader{X}{...}`` (auto-defined in notebook-extensions.sty)
      → label ``ch:X``
    - ``\lessonheader{X}{...}``  → label ``ch:X``
    These macros expand to ``\chapter{...}\label{ch:#1}`` so the labels
    exist in the .aux file but not as literal ``\label{}`` text in source.
    """
    labels = defaultdict(list)

    # Pattern for explicit \label{...}
    pattern = r'\\label\{([^}]+)\}'
    for i, line in enumerate(content.split('\n'), 1):
        for match in re.finditer(pattern, line):
            label = match.group(1)
            labels[label].append((i, filepath))

    # Pattern for macro-generated chapter labels (\moduleheader{X}{...} and
    # \lessonheader{X}{...}); both expand to \chapter{...}\label{ch:X}.
    macro_pattern = r'\\(?:moduleheader|lessonheader)\{([^}]+)\}'
    for i, line in enumerate(content.split('\n'), 1):
        for match in re.finditer(macro_pattern, line):
            generated_label = f'ch:{match.group(1)}'
            labels[generated_label].append((i, filepath))

    return dict(labels)


def extract_refs(content: str, filepath: str) -> list[tuple[int, str, str]]:
    """Extract all reference commands from LaTeX content.

    Returns list of (line_number, ref_type, label) tuples.
    """
    refs = []

    patterns = [
        (r'\\ref\{([^}]+)\}', 'ref'),
        (r'\\pageref\{([^}]+)\}', 'pageref'),
        (r'\\hyperref\[([^\]]+)\]', 'hyperref'),
        (r'\\autoref\{([^}]+)\}', 'autoref'),
        (r'\\nameref\{([^}]+)\}', 'nameref'),
        (r'\\eqref\{([^}]+)\}', 'eqref'),
    ]

    for i, line in enumerate(content.split('\n'), 1):
        # Comments are already stripped upstream (process_files); scan the live text.
        for pattern, ref_type in patterns:
            for match in re.finditer(pattern, line):
                label = match.group(1)
                refs.append((i, ref_type, label))

    return refs


def validate_refs(
    all_labels: dict[str, list[tuple[int, str]]],
    all_refs: list[tuple[str, int, str, str]],  # (file, line, ref_type, label)
) -> list[RefIssue]:
    """Validate that all references point to existing labels.

    Returns list of RefIssue for broken references.
    """
    issues = []

    for file, line, ref_type, label in all_refs:
        if label not in all_labels:
            issues.append(RefIssue(
                file=file,
                line=line,
                ref_type=ref_type,
                label=label,
                message=f"Undefined reference: \\{ref_type}{{{label}}}"
            ))

    return issues


def check_duplicate_labels(
    all_labels: dict[str, list[tuple[int, str]]]
) -> list[RefIssue]:
    """Check for duplicate label definitions."""
    issues = []

    for label, locations in all_labels.items():
        if len(locations) > 1:
            files = [f"{f}:{l}" for l, f in locations]
            issues.append(RefIssue(
                file=locations[0][1],
                line=locations[0][0],
                ref_type='label',
                label=label,
                message=f"Duplicate label '{label}' defined in: {', '.join(files)}"
            ))

    return issues


def process_files(filepaths: list[Path], verbose: bool = False) -> tuple[dict, list, list[RefIssue]]:
    """Process all files and collect labels/refs.

    Returns (all_labels, all_refs, issues).
    """
    all_labels: dict[str, list[tuple[int, str]]] = defaultdict(list)
    all_refs: list[tuple[str, int, str, str]] = []
    file_issues: list[RefIssue] = []

    for filepath in filepaths:
        if not filepath.exists():
            # An explicitly-named file that does not exist is an ERROR, not a silent skip — glob
            # expansion only ever yields existing paths, so a missing path was named explicitly.
            # Fail loud (guides-tooling#4 p14).
            file_issues.append(RefIssue(
                file=str(filepath),
                line=0,
                ref_type='file',
                label='',
                message=f"File not found: {filepath}"
            ))
            continue

        try:
            content = filepath.read_text(encoding='utf-8')
        except Exception as e:
            file_issues.append(RefIssue(
                file=str(filepath),
                line=0,
                ref_type='file',
                label='',
                message=f"Could not read file: {e}"
            ))
            continue

        # Strip LaTeX comments so a commented-out \label/\ref is not counted (guides-tooling#4 p11/p12).
        content = _strip_latex_comments(content)

        if verbose:
            print(f"Processing: {filepath}")

        # Extract labels
        file_labels = extract_labels(content, str(filepath))
        for label, locations in file_labels.items():
            all_labels[label].extend(locations)

        # Extract refs
        file_refs = extract_refs(content, str(filepath))
        for line, ref_type, label in file_refs:
            all_refs.append((str(filepath), line, ref_type, label))

    return dict(all_labels), all_refs, file_issues


def get_all_tex_files() -> list[Path]:
    """Get all .tex files across all volumes."""
    tex_files = []
    base = Path('.')

    # Find all volume directories
    for vol_dir in sorted(base.glob('vol*')):
        if vol_dir.is_dir():
            tex_files.extend(sorted(vol_dir.glob('**/*.tex')))

    # Also check shared/
    shared = base / 'shared'
    if shared.exists():
        tex_files.extend(sorted(shared.glob('*.tex')))

    return tex_files


def main():
    parser = argparse.ArgumentParser(
        description='Check cross-references in LaTeX files'
    )
    parser.add_argument(
        'files',
        nargs='*',
        help='LaTeX files to check (glob patterns supported)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Check all volumes'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print detailed processing info'
    )
    parser.add_argument(
        '--warn-duplicates',
        action='store_true',
        help='Warn about duplicate label definitions'
    )
    parser.add_argument(
        '--phantom-labels',
        type=Path,
        default=None,
        help=(
            'Path to a file listing labels that are emitted by LaTeX macros '
            "(one label per line) but are not visible to this validator's "
            r'regex scan. Use for labels emitted via \newcommand bodies in '
            '.sty files (e.g., chapter labels emitted by a \\moduleheader '
            'macro). Lines starting with # are treated as comments.'
        ),
    )

    args = parser.parse_args()

    # Collect files to process
    if args.all:
        filepaths = get_all_tex_files()
    elif args.files:
        filepaths = []
        for pattern in args.files:
            if '*' in pattern:
                filepaths.extend(Path('.').glob(pattern))
            else:
                filepaths.append(Path(pattern))
    else:
        parser.error("Specify files to check or use --all")

    if not filepaths:
        print("No files to check", file=sys.stderr)
        return 1

    print(f"Checking {len(filepaths)} files...")

    # Process all files
    all_labels, all_refs, file_issues = process_files(filepaths, args.verbose)

    # Merge in phantom labels (emitted by LaTeX macros, invisible to regex scan).
    phantom_count = 0
    if args.phantom_labels is not None:
        if not args.phantom_labels.exists():
            raise FileNotFoundError(
                f"--phantom-labels file not found: {args.phantom_labels}"
            )
        for raw in args.phantom_labels.read_text(encoding='utf-8').splitlines():
            label = raw.strip()
            if not label or label.startswith('#'):
                continue
            all_labels.setdefault(label, []).append(
                (0, f"<phantom:{args.phantom_labels}>")
            )
            phantom_count += 1

    # Validate references
    ref_issues = validate_refs(all_labels, all_refs)

    # Check for duplicates if requested
    dup_issues = []
    if args.warn_duplicates:
        dup_issues = check_duplicate_labels(all_labels)

    # Combine all issues
    all_issues = file_issues + ref_issues + dup_issues

    # Report results
    print(f"\nLabels defined: {len(all_labels)}"
          + (f" (incl. {phantom_count} phantom)" if phantom_count else ""))
    print(f"References found: {len(all_refs)}")

    if all_issues:
        print(f"\n❌ Found {len(all_issues)} issues:\n")

        # Group by file for readability
        by_file: dict[str, list[RefIssue]] = defaultdict(list)
        for issue in all_issues:
            by_file[issue.file].append(issue)

        for file, issues in sorted(by_file.items()):
            print(f"{file}:")
            for issue in sorted(issues, key=lambda x: x.line):
                print(f"  L{issue.line}: {issue.message}")
            print()

        return 1
    else:
        print("\n✅ All cross-references are valid!")
        return 0


if __name__ == '__main__':
    sys.exit(main())
