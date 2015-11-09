from collections import namedtuple
from jinja2 import Environment, PackageLoader
from pycobertura.cobertura import CoberturaDiff
from pycobertura.utils import green, rangify, red
from pycobertura.templates import filters
from tabulate import tabulate


env = Environment(loader=PackageLoader('pycobertura', 'templates'))
env.filters['line_status'] = filters.line_status_class
env.filters['line_reason'] = filters.line_reason_icon

row_attributes = [
    'class_filename',
    'total_statements',
    'total_misses',
    'line_rate'
]
class_row = namedtuple('ClassRow', row_attributes)
class_row_missed = namedtuple(
    'ClassRowMissed', row_attributes + ['missed_lines']
)


class Reporter(object):
    def __init__(self, cobertura):
        self.cobertura = cobertura

    def get_report_lines(self):
        lines = []

        for class_filename in self.cobertura.class_files():
            row = class_row_missed(
                class_filename,
                self.cobertura.total_statements(class_filename),
                self.cobertura.total_misses(class_filename),
                self.cobertura.line_rate(class_filename),
                self.cobertura.missed_lines(class_filename),
            )
            lines.append(row)

        footer = class_row_missed(
            'TOTAL',
            self.cobertura.total_statements(),
            self.cobertura.total_misses(),
            self.cobertura.line_rate(),
            [],  # dummy missed lines
        )
        lines.append(footer)

        return lines


class TextReporter(Reporter):
    def format_row(self, row):
        class_filename, total_lines, total_misses, line_rate, missed_lines = row

        line_rate = '%.2f%%' % (line_rate * 100)

        formatted_missed_lines = []
        for line_start, line_stop in rangify(missed_lines):
            if line_start == line_stop:
                formatted_missed_lines.append('%s' % line_start)
            else:
                line_range = '%s-%s' % (line_start, line_stop)
                formatted_missed_lines.append(line_range)
        formatted_missed_lines = ', '.join(formatted_missed_lines)

        row = class_row_missed(
            class_filename,
            total_lines,
            total_misses,
            line_rate,
            formatted_missed_lines,
        )

        return row

    def generate(self):
        lines = self.get_report_lines()

        formatted_lines = []
        for row in lines:
            formatted_row = self.format_row(row)
            formatted_lines.append(formatted_row)

        report = tabulate(
            formatted_lines,
            headers=['Filename', 'Stmts', 'Miss', 'Cover', 'Missing']
        )

        return report


class HtmlReporter(TextReporter):
    def __init__(self, *args, **kwargs):
        super(HtmlReporter, self).__init__(*args, **kwargs)

    def get_source(self, class_filename):
        lines = self.cobertura.class_file_source(class_filename)
        return lines

    def generate(self):
        lines = self.get_report_lines()

        formatted_lines = []
        for row in lines:
            formatted_row = self.format_row(row)
            formatted_lines.append(formatted_row)

        sources = []
        for class_filename in self.cobertura.class_files():
            source = self.get_source(class_filename)
            sources.append((class_filename, source))

        template = env.get_template('html.jinja2')
        return template.render(
            lines=formatted_lines[:-1],
            footer=formatted_lines[-1],
            sources=sources
        )


class DeltaReporter(object):
    def __init__(self, cobertura1, cobertura2, show_source=True):
        self.differ = CoberturaDiff(cobertura1, cobertura2)
        self.show_source = show_source

    def get_class_row(self, class_name):
        row_values = [
            class_name,
            self.differ.diff_total_statements(class_name),
            self.differ.diff_total_misses(class_name),
            self.differ.diff_line_rate(class_name),
        ]

        if self.show_source is True:
            missed_lines = self.differ.diff_missed_lines(class_name)
            row_values.append(missed_lines)
            row = class_row_missed(*row_values)
        else:
            row = class_row(*row_values)

        return row

    def get_footer_row(self):
        footer_values = [
            'TOTAL',
            self.differ.diff_total_statements(),
            self.differ.diff_total_misses(),
            self.differ.diff_line_rate(),
        ]

        if self.show_source:
            footer_values.append([])  # dummy missed lines
            footer = class_row_missed(*footer_values)
        else:
            footer = class_row(*footer_values)

        return footer

    def get_report_lines(self):
        lines = []

        for class_name in self.differ.class_files():
            class_row = self.get_class_row(class_name)
            if any(class_row[1:]):  # don't report unchanged class files
                lines.append(class_row)

        footer = self.get_footer_row()
        lines.append(footer)

        return lines


class TextReporterDelta(DeltaReporter):
    def __init__(self, *args, **kwargs):
        """
        Takes the same arguments as `DeltaReporter` but also takes the keyword
        argument `color` which can be set to True or False depending if the
        generated report should be colored or not (default `color=False`).
        """
        self.color = kwargs.pop('color', False)
        super(TextReporterDelta, self).__init__(*args, **kwargs)

    def format_row(self, row):
        total_statements = (
            '%+d' % row.total_statements
            if row.total_statements else '-'
        )
        line_rate = '%+.2f%%' % (row.line_rate * 100) if row.line_rate else '-'
        total_misses = '%+d' % row.total_misses if row.total_misses else '-'

        if self.color is True and total_misses != '-':
            colorize = [green, red][total_misses[0] == '+']
            total_misses = colorize(total_misses)

        if self.show_source is True:
            missed_lines = [
                '%s%d' % (['-', '+'][is_new], lno)
                for lno, is_new in row.missed_lines
            ]

            if self.color is True:
                missed_lines_colored = []
                for line in missed_lines:
                    colorize = [green, red][line[0] == '+']
                    colored_line = colorize(line)
                    missed_lines_colored.append(colored_line)
            else:
                missed_lines_colored = missed_lines

            missed_lines = ', '.join(missed_lines_colored)

        row = [
            row.class_filename,
            total_statements,
            total_misses,
            line_rate,
        ]

        if self.show_source is True:
            row.append(missed_lines)

        return row

    def generate(self):
        lines = self.get_report_lines()

        formatted_lines = []
        for row in lines:
            formatted_row = self.format_row(row)
            formatted_lines.append(formatted_row)

        headers = ['Filename', 'Stmts', 'Miss', 'Cover']

        if self.show_source is True:
            headers.append('Missing')

        report = tabulate(
            formatted_lines,
            headers=headers
        )

        return report


class HtmlReporterDelta(TextReporterDelta):
    def get_source_hunks(self, class_filename):
        hunks = self.differ.class_source_hunks(class_filename)
        return hunks

    def format_row(self, row):
        total_statements = (
            '%+d' % row.total_statements
            if row.total_statements else '-'
        )
        total_misses = '%+d' % row.total_misses if row.total_misses else '-'
        line_rate = '%+.2f%%' % (row.line_rate * 100) if row.line_rate else '-'

        if self.show_source is True:
            missed_lines = [
                '%s%d' % (['-', '+'][is_new], lno)
                for lno, is_new in row.missed_lines
            ]

        row_values = [
            row.class_filename,
            total_statements,
            total_misses,
            line_rate,
        ]

        if self.show_source is True:
            row_values.append(missed_lines)
            row = class_row_missed(*row_values)
        else:
            row = class_row(*row_values)

        return row

    def generate(self):
        lines = self.get_report_lines()

        formatted_lines = []
        for row in lines:
            formatted_row = self.format_row(row)
            formatted_lines.append(formatted_row)

        if self.show_source is True:
            sources = []
            for class_filename in self.differ.class_files():
                source_hunks = self.get_source_hunks(class_filename)
                if not source_hunks:
                    continue
                sources.append((class_filename, source_hunks))

        template = env.get_template('html-delta.jinja2')

        render_kwargs = {
            'lines': formatted_lines[:-1],
            'footer': formatted_lines[-1],
            'show_source': self.show_source,
        }

        if self.show_source is True:
            render_kwargs['sources'] = sources

        return template.render(**render_kwargs)
