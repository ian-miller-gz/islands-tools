import importlib.util
import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
  'release', ROOT / '.github' / 'release.py')
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)

DAY = 24 * 60 * 60
NOW = 1_800_000_000
CONFIG = 'tools: 0.1.0\ncompiler: g++\n\ndirectives:\n  engine:\n    ENGINE_VERSION: "0.3.5"\n'
MANIFEST = 'name: sound\nentry: libsound.so\nrelease: 0.3.5\n'
PYPROJECT = '[project]\nname = "islands-tools"\nversion = "0.3.5"\n'
PLUGINS = 'release: 0.3.5\nsound: 0.1\n'
SHAPES = {'engine': (release.CONFIG, CONFIG), 'bundle': (release.MANIFEST, MANIFEST),
          'tools': (release.PYPROJECT, PYPROJECT), 'plugins': (release.PLUGINS, PLUGINS)}


def test_parse_reads_three_numbers():
  assert release.parse('0.3.5') == (0, 3, 5)
  assert release.name((1, 10, 2)) == '1.10.2'


@pytest.mark.parametrize('bad', ['0.3', 'v0.3.5', '0.3.5-rc1', '', None])
def test_parse_refuses_other_shapes(bad):
  with pytest.raises(SystemExit):
    release.parse(bad)


def test_a_bundle_states_its_release_in_the_manifest():
  assert release.stated('name: Launcher\nrelease: 0.1.2\n') == '0.1.2'
  assert release.stated('name: Launcher\n') is None


def test_a_python_repo_states_its_release_in_pyproject():
  assert release.stated(PYPROJECT) == '0.3.5'
  assert release.stated('[project]\nname = "islands-tools"\n') is None


def test_a_numbered_file_names_its_component():
  assert release.kind(CONFIG) == 'engine'
  assert release.kind(MANIFEST) == 'bundle'
  assert release.kind(PYPROJECT) == 'tools'
  assert release.kind(PLUGINS) == 'plugins'
  assert release.kind('compiler: g++\n') is None


def test_config_reads_the_version_and_the_tools_requirement():
  assert release.stated(CONFIG) == '0.3.5'
  assert release.required(CONFIG) == '0.1.0'
  assert release.required('compiler: g++\n') is None
  assert release.stated('compiler: g++\n') is None


def test_stable_takes_x_y_0_or_a_patch_on_its_line():
  assert release.stable_shape((0, 4, 0)) == []
  assert release.stable_shape((0, 4, 1))
  assert release.stable_shape((0, 4, 1), (0, 4, 0)) == []
  assert release.stable_shape((0, 5, 1), (0, 4, 0))


def test_stable_raises_the_minor():
  assert release.stable_advance((0, 4, 0), (0, 3, 0)) == []
  assert release.stable_advance((1, 0, 0), (0, 9, 0)) == []
  assert release.stable_advance((0, 4, 0), None) == []
  assert release.stable_advance((0, 3, 0), (0, 3, 0))
  assert release.stable_advance((0, 2, 0), (0, 3, 0))
  assert '0.3.0' in release.stable_advance((0, 3, 0), (0, 3, 0))[0]
  assert release.stable_advance((0, 4, 3), (0, 4, 0)) == []
  assert release.stable_advance((0, 4, 0), (0, 4, 3))


def test_stable_waits_a_week():
  assert release.soak(NOW - 7 * DAY, NOW) == []
  assert release.soak(NOW - 6 * DAY - 3600, NOW)


def test_stable_takes_latest_or_one_commit_atop_it():
  assert release.promotion('head', 'latest', 'latest') == []
  assert release.promotion('head', 'head', 'head') == []
  assert release.promotion('head', 'head', 'elsewhere')


def test_latest_only_advances():
  assert release.latest_advance((0, 3, 1), (0, 3, 0)) == []
  assert release.latest_advance((0, 4, 0), None) == []
  assert release.latest_advance((0, 3, 0), (0, 3, 0))
  assert release.latest_advance((0, 3, 0), (0, 4, 0))


def test_latest_never_falls_behind_stable():
  assert release.latest_stable((0, 4, 1), (0, 4, 0)) == []
  assert release.latest_stable((0, 4, 0), (0, 4, 0)) == []
  assert release.latest_stable((0, 3, 6), (0, 4, 0))


def test_latest_is_tagged_at_the_tip():
  assert release.released((0, 3, 5), {'0.3.5'}) == []
  assert release.released((0, 3, 5), set())


def test_a_release_ref_names_the_tree_version():
  assert release.named('0.3.5', (0, 3, 5)) == []
  assert release.named('0.4.0', (0, 3, 5))


def test_a_working_branch_names_its_line():
  assert release.working('0.3', (0, 3, 4)) == []
  assert release.working('0.4', (0, 3, 4))


def test_a_feature_branch_names_an_open_line():
  assert release.line('0.3-enhance-ci') == '0.3'
  assert release.line('0.3-launcher') == '0.3'
  assert release.line('0.3') is None
  assert release.line('enhance-ci') is None
  assert release.line('0.3-Enhance') is None
  assert release.feature('0.3-enhance-ci', (0, 3, 4), True) == []
  assert release.feature('0.4-enhance-ci', (0, 3, 4), True)
  assert any('absent' in p for p in release.feature('0.3-enhance-ci', (0, 3, 4), False))


def test_a_released_tree_is_clean():
  assert release.clean(['src/a.cpp', 'src/readmeish.cpp', 'configs/make.yaml']) == []
  private = ['.' + name + '/a.md' for name in release.PRIVATE]
  hits = release.clean(private + ['CLAUDE' + '.md', 'README.md',
                                  'src/README.md', 'docs/a.md', 'src/a.cpp'])
  assert len(hits) == len(private) + 4


def test_release_lines_are_linear():
  assert release.linear([]) == []
  assert release.linear(['abc'])


def test_tools_requirement_is_a_tag_on_the_pin():
  assert release.tools('compiler: g++\n', set()) == []
  assert release.tools(CONFIG, {'0.1.0'}) == []
  assert release.tools(CONFIG, {'0.2.0'})
  assert release.tools(CONFIG, set())


def test_a_bump_edits_the_version_line_alone():
  edits = ['-    ENGINE_VERSION: "0.3.5"', '+    ENGINE_VERSION: "0.4.0"']
  assert release.bump({release.CONFIG}, edits)
  assert release.bump(set(), [])
  assert not release.bump({release.CONFIG, 'src/a.cpp'}, edits)
  assert not release.bump({release.CONFIG}, edits + ['+compiler: clang++'])


def test_a_bump_edits_the_release_line_of_any_numbered_file():
  assert release.bump({release.MANIFEST}, ['-release: 0.1.2', '+release: 0.2.0'])
  assert release.bump({release.PYPROJECT}, ['-version = "0.3.0"', '+version = "0.4.0"'])
  assert not release.bump({release.MANIFEST}, ['-release: 0.1.2', '+release: 0.2.0', '+entry: x'])
  assert not release.bump({release.PYPROJECT, 'make/version.py'}, ['-version = "0.3.0"', '+version = "0.4.0"'])


class Repo:
  def __init__(self, path):
    self.path = path
    self.env = {**os.environ, 'GIT_AUTHOR_NAME': 'ci', 'GIT_AUTHOR_EMAIL': 'ci@example.com',
                'GIT_COMMITTER_NAME': 'ci', 'GIT_COMMITTER_EMAIL': 'ci@example.com'}
    self.git('init', '-q', '-b', 'work')

  def git(self, *words, when=None):
    env = dict(self.env)
    if when is not None:
      env['GIT_AUTHOR_DATE'] = env['GIT_COMMITTER_DATE'] = f'{when} +0000'
    return subprocess.run(['git', *words], cwd=self.path, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()

  def commit(self, version, when, extra=None, shape='engine'):
    path, text = SHAPES[shape]
    (self.path / path).parent.mkdir(exist_ok=True)
    (self.path / path).write_text(text.replace('0.3.5', version))
    if extra:
      (self.path / extra).write_text('x\n')
    self.git('add', '-A')
    self.git('commit', '-q', '-m', version, when=when)
    return self.git('rev-parse', 'HEAD')

  def line(self, name, commit):
    self.git('update-ref', f'refs/remotes/origin/{name}', commit)


@pytest.fixture
def repo(tmp_path, monkeypatch):
  monkeypatch.chdir(tmp_path)
  return Repo(tmp_path)


def test_a_soaked_latest_promotes_by_one_release_number_commit(repo):
  older = repo.commit('0.3.0', NOW - 30 * DAY)
  soaked = repo.commit('0.3.5', NOW - 10 * DAY)
  repo.git('tag', '0.3.5')
  repo.line('stable', older)
  repo.line('latest', soaked)
  head = repo.commit('0.4.0', NOW - 60)
  assert release.content(head) == soaked
  assert release.check_stable(older, head, NOW) == []
  assert release.check_stable(release.NONE, head, NOW) == []
  assert release.check_stable(older, head, NOW - 5 * DAY)
  assert release.check_branch('0.4.0', head) == []
  assert release.check_branch('0.5.0', head)
  assert release.check_branch('feature', head) == []
  assert release.check_branch('0.4', head) == []
  assert release.check_branch('0.3', head)


def test_a_promotion_carrying_more_than_the_number_is_refused(repo):
  soaked = repo.commit('0.3.5', NOW - 10 * DAY)
  repo.line('stable', soaked)
  repo.line('latest', soaked)
  head = repo.commit('0.4.0', NOW - 60, extra='patch.txt')
  assert release.content(head) == head
  problems = release.check_stable(release.NONE, head, NOW)
  assert any('diverges' in problem for problem in problems)
  assert any('soaked' in problem for problem in problems)


def test_the_tip_of_latest_itself_promotes_once_soaked(repo):
  older = repo.commit('0.3.0', NOW - 30 * DAY)
  head = repo.commit('0.4.0', NOW - 8 * DAY, extra='patch.txt')
  repo.line('stable', older)
  repo.line('latest', head)
  assert release.content(head) == head
  assert release.check_stable(older, head, NOW) == []
  assert release.check_stable(older, head, NOW - 2 * DAY)


def test_latest_takes_a_tagged_advance_ahead_of_stable(repo):
  stable = repo.commit('0.4.0', NOW - 10 * DAY)
  repo.line('stable', stable)
  repo.line('latest', stable)
  head = repo.commit('0.4.1', NOW - 60)
  assert release.check_latest(stable, head)
  repo.git('tag', '0.4.1')
  assert release.check_latest(stable, head) == []
  assert release.check_latest(release.NONE, head) == []
  behind = repo.commit('0.3.9', NOW - 30)
  repo.git('tag', '0.3.9')
  assert release.check_latest(head, behind)


def test_a_tag_names_the_tree_version_and_the_tree_is_clean(repo):
  head = repo.commit('0.4.0', NOW - 60)
  assert release.named('0.4.0', release.version(head)) == []
  assert release.clean(release.tree(head)) == []
  dirty = repo.commit('0.4.0', NOW - 30, extra='README.md')
  assert release.clean(release.tree(dirty))


def test_a_promotion_takes_a_tagged_descendant(repo):
  older = repo.commit('0.3.0', NOW - 30 * DAY)
  repo.line('stable', older)
  repo.line('latest', older)
  head = repo.commit('0.3.1', NOW - 60)
  repo.git('tag', '0.3.1')
  repo.git('update-ref', 'refs/remotes/origin/latest', older)
  assert release.check_promote('latest', '0.3.1', NOW) == []
  aside = repo.commit('0.3.2', NOW - 30)
  repo.git('tag', '0.3.2')
  repo.line('latest', head)
  assert release.check_promote('latest', '0.3.2', NOW) == []
  repo.git('update-ref', 'refs/remotes/origin/latest', aside)
  assert release.forward(aside, head)


def test_an_unnumbered_line_holds_nothing_back(repo):
  config = repo.path / 'configs'
  config.mkdir(exist_ok=True)
  (config / 'make.yaml').write_text('compiler: g++\n')
  repo.git('add', '-A')
  repo.git('commit', '-q', '-m', 'init', when=NOW - 30 * DAY)
  init = repo.git('rev-parse', 'HEAD')
  assert release.numbered(init) is None
  repo.line('stable', init)
  repo.line('latest', init)
  head = repo.commit('0.1.0', NOW - 60)
  repo.git('tag', '0.1.0')
  assert release.check_latest(init, head) == []


def test_notes_table_the_engine_and_every_pin(repo):
  head = repo.commit('0.4.0', NOW - 60)
  table = release.notes('0.4.0', head).splitlines()
  assert table[0] == '| component | release | commit |'
  assert table[2] == f'| engine | 0.4.0 | {head} |'


@pytest.mark.parametrize('shape', ['bundle', 'tools', 'plugins'])
def test_a_bundle_or_tools_repo_follows_the_same_rules(repo, shape):
  older = repo.commit('0.3.0', NOW - 30 * DAY, shape=shape)
  repo.git('tag', '0.3.0')
  repo.line('stable', older)
  repo.line('latest', older)
  patched = repo.commit('0.3.1', NOW - 10 * DAY, extra='patch.txt', shape=shape)
  assert release.check_latest(older, patched)
  repo.git('tag', '0.3.1')
  assert release.check_latest(older, patched) == []
  assert release.check_promote('latest', '0.3.1', NOW) == []
  repo.line('latest', patched)
  head = repo.commit('0.4.0', NOW - 60, shape=shape)
  assert release.content(head) == patched
  assert release.check_stable(older, head, NOW) == []
  assert release.check_branch('0.4.0', head) == []
  assert release.check_branch('0.4-ci', head)
  table = release.notes('0.4.0', head).splitlines()
  assert table[2] == f'| {shape} | 0.4.0 | {head} |'

