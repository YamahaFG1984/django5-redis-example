"""
把源码同步进 HTML 文档，保证文档里的代码与仓库代码完全一致。

用法（在仓库根目录执行）：
    python3 docs/tools/sync_code.py

在 HTML 中这样声明要嵌入的代码：
    <code class="language-python"
          data-include="Chapter03/mysite/blog/services/pageviews.py::record_view"></code>

data-include 支持四种写法：
    path                      -> 整个文件
    path::函数名 / 类名.方法名  -> 用 ast 定位到这个函数或类（含装饰器）
    path::L10-30              -> 第 10~30 行
    path::#step-04            -> 从包含 "# ---- step-04" 的分隔注释开始，到下一个分隔注释为止
"""
import ast
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs'
PATTERN = re.compile(
    r'(<code\b[^>]*\bdata-include="([^"]+)"[^>]*>)(.*?)(</code>)', re.S
)


def find_symbol(tree, dotted):
    nodes = tree.body
    found = None
    for part in dotted.split('.'):
        found = next(
            (
                n for n in nodes
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.name == part
            ),
            None,
        )
        if found is None:
            raise LookupError(dotted)
        nodes = found.body
    return found


def extract(spec):
    path, _, selector = spec.partition('::')
    source = (ROOT / path).read_text(encoding='utf-8')
    lines = source.splitlines()
    if not selector:
        return source.rstrip('\n')
    if selector.startswith('#'):
        marks = [i for i, line in enumerate(lines, 1) if line.startswith('# ---')]
        start = next(i for i in marks if selector[1:] in lines[i - 1])
        later = [i for i in marks if i > start]
        end = (later[0] - 1) if later else len(lines)
        while not lines[end - 1].strip():
            end -= 1
    elif re.fullmatch(r'L\d+-\d+', selector):
        start, end = map(int, selector[1:].split('-'))
    else:
        node = find_symbol(ast.parse(source), selector)
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        end = node.end_lineno
    snippet = lines[start - 1:end]
    # 去掉公共缩进，方法片段也能从第 0 列开始展示
    indent = min(
        (len(line) - len(line.lstrip()) for line in snippet if line.strip()),
        default=0,
    )
    return '\n'.join(line[indent:] for line in snippet)


def main():
    changed = 0
    for page in sorted(DOCS.rglob('*.html')):
        text = page.read_text(encoding='utf-8')

        def repl(m):
            return m.group(1) + html.escape(extract(m.group(2)), quote=False) + m.group(4)

        new = PATTERN.sub(repl, text)
        if new != text:
            page.write_text(new, encoding='utf-8')
            changed += 1
            print(f'updated {page.relative_to(ROOT)}')
    print(f'{changed} file(s) updated')


if __name__ == '__main__':
    sys.exit(main())
