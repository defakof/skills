#!/usr/bin/env python3
"""Install the skills from this repository for Claude Code and/or Google Antigravity.

    python install.py                         # Claude Code, personal (~/.claude/skills)
    python install.py claude --project DIR    # Claude Code, one project (DIR/.claude/skills)
    python install.py antigravity             # Antigravity, global (~/.gemini/config/skills)
    python install.py antigravity --project DIR   # Antigravity workspace (DIR/.agents/skills)
    python install.py antigravity-cli         # Antigravity CLI (~/.gemini/antigravity-cli/skills)
    python install.py all                     # Claude Code + Antigravity, personal/global
    python install.py --list                  # show what would be installed where
    python install.py claude --uninstall      # remove

Options: --skill NAME (default: every folder in skills/), --link (symlink instead of copy,
for development), --force (replace an existing install without asking).
"""

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(HERE, 'skills')
HOME = os.path.expanduser('~')

TARGETS = {
    # name: (global dir, project-relative dir)
    'claude': (os.path.join(HOME, '.claude', 'skills'), os.path.join('.claude', 'skills')),
    'antigravity': (os.path.join(HOME, '.gemini', 'config', 'skills'), os.path.join('.agents', 'skills')),
    'antigravity-cli': (os.path.join(HOME, '.gemini', 'antigravity-cli', 'skills'), os.path.join('.agents', 'skills')),
}


def available_skills():
    return sorted(n for n in os.listdir(SKILLS_DIR)
                  if os.path.isfile(os.path.join(SKILLS_DIR, n, 'SKILL.md')))


def ignore(_dir, names):
    return [n for n in names if n in ('__pycache__', '.pytest_cache') or n.endswith(('.pyc', '.bak'))]


def install_one(skill, dest_root, link, force, uninstall):
    src = os.path.join(SKILLS_DIR, skill)
    dest = os.path.join(dest_root, skill)
    exists = os.path.lexists(dest)
    if uninstall:
        if not exists:
            print(f'  {dest}: not installed')
            return
        if os.path.islink(dest) or os.path.isfile(dest):
            os.remove(dest)
        else:
            shutil.rmtree(dest)
        print(f'  removed {dest}')
        return
    if exists:
        if not force:
            ans = input(f'  {dest} exists. Replace it? [y/N] ').strip().lower()
            if ans not in ('y', 'yes'):
                print('  skipped')
                return
        if os.path.islink(dest) or os.path.isfile(dest):
            os.remove(dest)
        else:
            shutil.rmtree(dest)
    os.makedirs(dest_root, exist_ok=True)
    if link:
        os.symlink(src, dest, target_is_directory=True)
        print(f'  linked {dest} -> {src}')
    else:
        shutil.copytree(src, dest, ignore=ignore)
        print(f'  installed {dest}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('target', nargs='?', default='claude', choices=list(TARGETS) + ['all'])
    ap.add_argument('--project', help='install into this project/workspace instead of globally')
    ap.add_argument('--skill', action='append', help='skill folder name (default: all)')
    ap.add_argument('--link', action='store_true', help='symlink instead of copying')
    ap.add_argument('--force', action='store_true', help='replace existing installs without asking')
    ap.add_argument('--uninstall', action='store_true')
    ap.add_argument('--list', action='store_true', help='only print the plan')
    args = ap.parse_args()

    skills = args.skill or available_skills()
    for s in skills:
        if not os.path.isfile(os.path.join(SKILLS_DIR, s, 'SKILL.md')):
            ap.error(f'unknown skill {s!r}; available: {", ".join(available_skills())}')
    targets = ['claude', 'antigravity'] if args.target == 'all' else [args.target]
    for t in targets:
        glob_dir, proj_rel = TARGETS[t]
        root = os.path.join(os.path.abspath(args.project), proj_rel) if args.project else glob_dir
        print(f'{t}: {root}')
        for s in skills:
            if args.list:
                print(f'  would install {os.path.join(root, s)}')
            else:
                install_one(s, root, args.link, args.force, args.uninstall)
    if not args.list and not args.uninstall:
        print('Done. Start a new Claude Code / Antigravity session to pick the skill up.')
    if sys.version_info < (3, 8):
        print('warning: the bethesda-esp tool needs Python 3.8 or newer')
    return 0


if __name__ == '__main__':
    sys.exit(main())
