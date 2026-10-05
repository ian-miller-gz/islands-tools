import argparse
import re
import subprocess
import sys
import time

VERSION = re.compile(r'^\s*ENGINE_VERSION:\s*"([^"]*)"', re.M)
RELEASED = re.compile(r'^release:\s*(\S+)', re.M)
PROJECT = re.compile(r'^version\s*=\s*"([^"]*)"', re.M)
TOOLS = re.compile(r'^tools:\s*(\S+)', re.M)
SOUND = re.compile(r'^sound:\s*(\S+)', re.M)
RELEASE = re.compile(r'^\d+\.\d+\.\d+$')
WORKING = re.compile(r'^\d+\.\d+$')
LINE = re.compile(r'^(\d+\.\d+)-[a-z0-9]+(?:-[a-z0-9]+)*$')
NONE = '0' * 40
WEEK = 7 * 24 * 60 * 60
DAY = 24 * 60 * 60
CONFIG = 'configs/make.yaml'
MANIFEST = 'manifest.yaml'
PYPROJECT = 'pyproject.toml'
PLUGINS = 'plugins.yaml'
NUMBERED = {CONFIG: ('engine', VERSION), MANIFEST: ('bundle', RELEASED), PYPROJECT: ('tools', PROJECT),
            PLUGINS: ('plugins', RELEASED)}
TOOL = 'submodules/islands-tools'
PRIVATE = ('agents', 'claude', 'recordings')
FORBIDDEN = tuple('.' + name for name in PRIVATE) + ('CLAUDE' + '.md', 'docs', 'temp')
README = re.compile(r'(^|/)readme(\.|$)', re.I)


def git(*words, cwd=None):
  done = subprocess.run(['git', *words], cwd=cwd, capture_output=True, text=True)
  if done.returncode:
    raise SystemExit(f'git {" ".join(words)}: {done.stderr.strip()}')
  return done.stdout


def parse(release):
  if not RELEASE.match(release or ''):
    raise SystemExit(f'release {release!r} malformed')
  return tuple(int(part) for part in release.split('.'))


def name(release):
  return '.'.join(str(part) for part in release)


def stated(text):
  found = VERSION.search(text) or RELEASED.search(text) or PROJECT.search(text)
  return found.group(1) if found else None


def kind(text):
  if SOUND.search(text):
    return 'plugins'
  for component, pattern in NUMBERED.values():
    if pattern.search(text):
      return component
  return None


def required(text):
  found = TOOLS.search(text)
  return found.group(1) if found else None


def config(commit):
  for path in NUMBERED:
    done = subprocess.run(['git', 'show', f'{commit}:{path}'], capture_output=True, text=True)
    if done.returncode == 0:
      return done.stdout
  raise SystemExit(f'{CONFIG} absent at {commit}')


def version(commit):
  return parse(stated(config(commit)))


def numbered(commit):
  release = stated(config(commit))
  return parse(release) if release else None


def exists(commit):
  return bool(commit) and commit != NONE and subprocess.run(
    ['git', 'cat-file', '-e', f'{commit}^{{commit}}'], capture_output=True).returncode == 0


def tip(line):
  return git('rev-parse', '--verify', f'refs/remotes/origin/{line}').strip()


def parent(commit):
  parents = git('rev-list', '--parents', '-1', commit).split()[1:]
  return parents[0] if parents else None


def committed(commit):
  return int(git('log', '-1', '--format=%ct', commit).strip())


def tagged(commit, cwd=None):
  return set(git('tag', '--points-at', commit, cwd=cwd).split())


def files(base, head):
  return set(git('diff', '--name-only', base, head).split())


def hunk(base, head):
  lines = git('diff', '-U0', base, head, '--', *NUMBERED).splitlines()
  return [line for line in lines
          if line[:1] in ('+', '-') and line[:3] not in ('+++', '---')]


def tree(commit):
  return git('ls-tree', '-r', '--name-only', commit).splitlines()


def merges(before, head):
  return git('rev-list', '--merges', f'{before}..{head}').split() if exists(before) else []


def pin(head):
  words = git('ls-tree', head, '--', TOOL).split()
  return words[2] if len(words) > 2 else None


def pinned(head):
  sha = pin(head)
  if sha is None:
    return None
  git('submodule', 'update', '--init', '--', TOOL)
  git('fetch', '--tags', '--quiet', 'origin', cwd=TOOL)
  return tagged(sha, cwd=TOOL)


def bump(changed, edits):
  patterns = [pattern for _, pattern in NUMBERED.values()]
  return (changed <= set(NUMBERED)
          and all(any(pattern.match(line[1:]) for pattern in patterns) for line in edits))


def content(head):
  base = parent(head)
  if base and bump(files(base, head), hunk(base, head)):
    return base
  return head


def stable_shape(release, previous=None):
  if release[2] != 0 and (previous is None or release[:2] != previous[:2]):
    return [f'stable {name(release)} carries a patch number off its line']
  return []


def stable_advance(release, previous):
  if previous is None:
    return []
  if release[:2] == previous[:2]:
    return [] if release > previous else [f'{name(release)} does not pass stable {name(previous)}']
  if release[:2] < previous[:2]:
    return [f'minor unraised from stable {name(previous)}']
  return []


def soak(when, now):
  if now - when >= WEEK:
    return []
  return [f'soaked {(now - when) / DAY:.1f} of 7 days']


def promotion(head, promoted, latest):
  if latest in (promoted, head):
    return []
  return ['candidate diverges from latest']


def latest_advance(release, previous):
  if previous is not None and release <= previous:
    return [f'{name(release)} does not pass latest {name(previous)}']
  return []


def latest_stable(release, stable):
  if stable is not None and release < stable:
    return [f'latest {name(release)} behind stable {name(stable)}']
  return []


def released(release, tags):
  if name(release) not in tags:
    return [f'tag {name(release)} absent']
  return []


def named(label, release):
  if parse(label) != release:
    return [f'{label} states {name(release)}']
  return []


def clean(paths):
  hits = [path for path in paths
          if path.split('/')[0] in FORBIDDEN or README.search(path)]
  return [f'{path} present' for path in sorted(hits)]


def linear(commits):
  return [f'merge commit {commit}' for commit in commits]


def tools(text, tags):
  wanted = required(text)
  if wanted is None or tags is None or wanted in tags:
    return []
  carried = ' '.join(sorted(tags)) or 'untagged'
  return [f'tools {wanted} required, pin {carried}']


def check_stable(before, head, now):
  release = version(head)
  previous = numbered(before) if exists(before) else None
  promoted = content(head)
  patch = previous is not None and release[:2] == previous[:2]
  return (stable_shape(release, previous) + stable_advance(release, previous)
          + promotion(head, promoted, tip('latest'))
          + ([] if patch else soak(committed(promoted), now)))


def check_latest(before, head):
  release = version(head)
  previous = numbered(before) if exists(before) else None
  return (latest_advance(release, previous) + latest_stable(release, numbered(tip('stable')))
          + released(release, tagged(head)))


def check_line(line, before, head, now):
  if line == 'stable':
    problems = check_stable(before, head, now)
  else:
    problems = check_latest(before, head)
  problems += clean(tree(head)) + linear(merges(before, head))
  return problems + tools(config(head), pinned(head))


def check_tag(label, head):
  return named(label, version(head)) + clean(tree(head)) + tools(config(head), pinned(head))


def line(label):
  found = LINE.match(label)
  return found.group(1) if found else None


def opened(line):
  return subprocess.run(['git', 'ls-remote', '--exit-code', '--heads', 'origin', line],
                        capture_output=True).returncode == 0


def working(label, release):
  if tuple(int(part) for part in label.split('.')) != release[:2]:
    return [f'{label} states {name(release)}']
  return []


def feature(label, release, exists):
  problems = working(line(label), release)
  if not exists:
    problems.append(f'working branch {line(label)} absent')
  return problems


def ancestor(base, head):
  return subprocess.run(['git', 'merge-base', '--is-ancestor', base, head],
                        capture_output=True).returncode == 0


def forward(base, head):
  return [] if ancestor(base, head) else [f'{name(version(head))} does not descend from the line']


def check_promote(line, label, now):
  head = git('rev-parse', '--verify', f'refs/tags/{label}^{{commit}}').strip()
  before = tip(line)
  problems = named(label, version(head)) + forward(before, head)
  return problems + check_line(line, before, head, now)


def check_branch(label, head):
  release = version(head)
  if RELEASE.match(label):
    return named(label, release)
  if WORKING.match(label):
    return working(label, release)
  if line(label):
    return feature(label, release, opened(line(label)))
  return []


def notes(label, head):
  text = config(head)
  rows = [(kind(text), name(version(head)), head)]
  for line in git('ls-tree', head).splitlines():
    mode, sort, sha, path = line.replace('\t', ' ').split(maxsplit=3)
    if sort == 'commit':
      rows.append((path.split('/')[-1], required(text) if path == TOOL else '', sha))
  body = ['| component | release | commit |', '|---|---|---|']
  body += [f'| {component} | {release} | {sha} |' for component, release, sha in rows]
  return '\n'.join(body) + '\n'


def main(argv):
  parser = argparse.ArgumentParser(prog='release')
  parser.add_argument('kind', choices=('line', 'tag', 'branch', 'notes', 'promote'))
  parser.add_argument('name')
  parser.add_argument('head')
  parser.add_argument('--before', default=NONE)
  options = parser.parse_args(argv)
  if options.kind == 'notes':
    sys.stdout.write(notes(options.name, options.head))
    return 0
  if options.kind == 'line':
    problems = check_line(options.name, options.before, options.head, int(time.time()))
  elif options.kind == 'promote':
    problems = check_promote(options.name, options.head, int(time.time()))
  elif options.kind == 'tag':
    problems = check_tag(options.name, options.head)
  else:
    problems = check_branch(options.name, options.head)
  for problem in problems:
    print(problem, file=sys.stderr)
  print(f'{options.kind} {options.name}: {"refused" if problems else "ok"}')
  return 1 if problems else 0


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
