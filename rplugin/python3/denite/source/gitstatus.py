# ============================================================================
# FILE: gitstatus.py
# AUTHOR: Qiming Zhao <chemzqm@gmail.com>
# License: MIT license
# ============================================================================
# pylint: disable=E0401,C0411
import os
import re
import subprocess
import shlex
from .base import Base
from denite import util
from ..kind.file import Kind as File

EMPTY_LINE = re.compile(r"^\s*$")
STATUS_MAP = {
    ' ': (' ', ''),
    'M': ('~', 'modified'),
    'A': ('+', 'added'),
    'D': ('-', 'deleted'),
    'R': ('→', 'renamed'),
    'C': ('C', 'copied'),
    'U': ('U', 'updated'),
    '?': ('?', 'untracked'),
}


def _find_root(path):
    while True:
        if path == '/' or os.path.ismount(path):
            return None
        p = os.path.join(path, '.git')
        if os.path.isdir(p):
            return path
        path = os.path.dirname(path)


def _parse_line(line, root):
    path = os.path.join(root, line[3:])
    index_symbol, index_desc = STATUS_MAP[line[0]]
    tree_symbol, tree_desc = STATUS_MAP[line[1]]
    if tree_desc == index_desc:
        tree_desc = ''
    word = "{0}{1} {2} {3} {4}".format(index_symbol, tree_symbol, index_desc.ljust(12), tree_desc.ljust(12), line[3:],)

    return {
        'word': word,
        'action__path': path,
        'source__root': root,
        'source__staged': index_symbol not in [' ', '?'],
        'source__tree': tree_symbol not in [' ', '?']
    }

def run_command(commands, cwd, encoding='utf-8'):
    try:
        p = subprocess.run(commands,
                           cwd=cwd,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        return []

    return p.stdout.decode(encoding).split('\n')


class Source(Base):
    def __init__(self, vim):
        super().__init__(vim)
        self.name = 'gitstatus'
        self.kind = Kind(vim)

    def on_init(self, context):
        cwd = os.path.normpath(self.vim.eval('getcwd()'))
        context['__root'] = _find_root(cwd)

    def highlight(self):
        self.vim.command('highlight deniteGitStatusTracked guifg=#009900 ctermfg=79')
        self.vim.command('highlight deniteGitStatusUntracked guifg=#ff2222 ctermfg=79')

    def define_syntax(self):
        self.vim.command(r'syntax match deniteGitStatusTracked /^[*[:space:]][^[:space:]?].*$/') # +
        self.vim.command(r'syntax match deniteGitStatusUntracked /^[*[:space:]][[:space:]?].*$/') # +

    def gather_candidates(self, context):
        root = context['__root']
        if not root:
            return []
        args = ['git', 'status', '--porcelain', '-uall']
        self.print_message(context, ' '.join(args))
        lines = run_command(args, root)
        candidates = []

        for line in lines:
            if EMPTY_LINE.fullmatch(line):
                continue
            candidates.append(_parse_line(line, root))

        return candidates


class Kind(File):
    def __init__(self, vim):
        super().__init__(vim)

        self.persist_actions += ['reset', 'add']  # pylint: disable=E1101
        self.redraw_actions += ['reset', 'add', 'commit']  # pylint: disable=E1101
        self.name = 'gitstatus'

        val = self.vim.call('exists', ':Rm')
        if val == 2:
            self.remove = 'rm'
        elif self.vim.call('executable', 'rmtrash'):
            self.remove = 'rmtrash'
        else:
            self.remove = 'delete'

    def action_patch(self, context):
        args = []
        root = context['targets'][0]['source__root']
        for target in context['targets']:
            filepath = target['action__path']
            args.append(os.path.relpath(filepath, root))
        self.vim.command('terminal git add ' + ' '.join(args) + ' --patch')

    def action_add(self, context):
        args = ['git', 'add']
        root = context['targets'][0]['source__root']
        for target in context['targets']:
            filepath = target['action__path']
            args.append(os.path.relpath(filepath, root))
        run_command(args, root)

    # diff action
    def action_delete(self, context):
        target = context['targets'][0]
        root = target['source__root']

        preview_window = self.__get_preview_window()
        if (preview_window and self._previewed_target == target):
            self.vim.command('pclose!')
        else:
            relpath = os.path.relpath(target['action__path'], root)
            prefix = ''
            if target['source__staged']:
                if target['source__tree']:
                    if util.input(self.vim, context, 'Diff cached?[y/n]', 'y') == 'y':
                        prefix = '--cached '
                else:
                    prefix = '--cached '

            prev_id = self.vim.call('win_getid')
            self.vim.call('easygit#diffPreview', prefix + relpath)
            self.vim.call('win_gotoid', prev_id)
            self._previewed_target = target


    def action_reset(self, context):
        cwd = os.path.normpath(self.vim.eval('expand("%:p:h")'))
        for target in context['targets']:
            filepath = target['action__path']
            root = target['source__root']
            path = os.path.relpath(filepath, root)
            if target['source__tree'] and target['source__staged']:
                res = util.input(self.vim, context, 'Select action reset or checkout [r/c]')
                if res == 'c':
                    args = 'git checkout -- ' + path
                    run_command(shlex.split(args), root)
                elif res == 'r':
                    args = 'git reset HEAD -- ' + path
                    run_command(shlex.split(args), root)
            elif target['source__tree']:
                args = 'git checkout -- ' + path
                run_command(shlex.split(args), root)
            elif target['source__staged']:
                args = 'git reset HEAD -- ' + path
                run_command(shlex.split(args), root)
            else:
                if self.remove == 'rm':
                    self.vim.command('Rm ' + os.path.relpath(filepath, cwd))
                elif self.remove == 'rmtrash':
                    run_command(['rmtrash', filepath], root)
                else:
                    self.vim.call('delete', filepath)
            self.vim.command('checktime')

    def action_commit(self, context):
        root = context['targets'][0]['source__root']
        message = util.input(self.vim, context, 'Commit message: ')
        args = ['-v', '-m', message]

        if self.vim.call('exists', ':Gcommit'):
            self.vim.command('Gcommit ' + ' '.join(args))
            return

        for target in context['targets']:
            filepath = target['action__path']
            path = os.path.relpath(filepath, root)
            args.append(path)

        self.vim.call('easygit#commit', ' '.join(args))
