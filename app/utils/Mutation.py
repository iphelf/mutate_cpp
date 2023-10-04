# coding=utf-8

import json
import re
from typing import Dict, List, Tuple
from app.utils.Replacement import Replacement


class StringLiteralFinder:
    def __init__(self, line):
        self.string_literals = []  # type: List[Tuple[int, int]]

        for match in re.finditer(re.compile("\".*?\""), line):
            self.string_literals.append(match.span())

    def is_in_string_literal(self, index):
        for (string_start, string_end) in self.string_literals:
            if string_start < index < string_end:
                return True

        return False


##############################################################################

class SimplePattern:
    def __init__(self, replacement_patterns):
        self.replacement_patterns = replacement_patterns  # type: Dict[str, List[str]]

    def mutate(self, line):
        result = []  # type: List[Replacement]

        string_finder = StringLiteralFinder(line)

        for replacement_pattern in self.replacement_patterns.keys():
            for occurrence in [match for match in re.finditer(re.compile(replacement_pattern), line)]:
                if string_finder.is_in_string_literal(occurrence.start()):
                    continue

                for replacement_str in self.replacement_patterns[replacement_pattern]:
                    result.append(Replacement(start_col=occurrence.start(),
                                              end_col=occurrence.end(),
                                              old_val=line[occurrence.start():occurrence.end()],
                                              new_val=replacement_str))

        return result

    def __repr__(self):
        return str(self.replacement_patterns)


##############################################################################

class Mutator:
    mutator_id: str
    description: str
    tags: list[str]

    def find_mutations(self, line: str) -> list[Replacement]: ...


class LineDeletionMutator(Mutator):
    mutator_id = 'lineDeletion'
    description = 'Deletes a whole line.'
    tags = ['naive']

    def __init__(self):
        pass

    # noinspection PyMethodMayBeStatic
    def find_mutations(self, line):
        return [Replacement(start_col=0,
                            end_col=len(line) - 1,
                            old_val=line,
                            new_val=None)]


class LogicalOperatorMutator(Mutator):
    mutator_id = 'logicalOperator'
    description = 'Replaces logical operators.'
    tags = ['logical', 'operator']

    def __init__(self):
        self.pattern = SimplePattern({
            ' && ': [' || '],
            ' and ': [' or '],
            ' \|\| ': [' && '],
            ' or ': [' and '],
            '!': [''],
            'not': ['']
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


class ComparisonOperatorMutator(Mutator):
    mutator_id = 'comparisonOperator'
    description = 'Replaces comparison operators.'
    tags = ['operator', 'comparison']

    def __init__(self):
        self.pattern = SimplePattern({
            ' == ': [' != ', ' < ', ' > ', ' <= ', ' >= '],
            ' != ': [' == ', ' < ', ' > ', ' <= ', ' >= '],
            ' < ': [' == ', ' != ', ' > ', ' <= ', ' >= '],
            ' > ': [' == ', ' != ', ' < ', ' <= ', ' >= '],
            ' <= ': [' == ', ' != ', ' < ', ' > ' ' >= '],
            ' >= ': [' == ', ' != ', ' < ', ' > ' ' <= ']
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


class IncDecOperatorMutator(Mutator):
    mutator_id = 'incDecOperator'
    description = 'Swaps increment and decrement operators.'
    tags = ['operator', 'artithmetic']

    def __init__(self):
        self.pattern = SimplePattern({
            '\+\+': ['--'],
            '--': ['++'],
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


class AssignmentOperatorMutator(Mutator):
    mutator_id = 'assignmentOperator'
    description = 'Replaces assignment operators.'
    tags = ['operator']

    def __init__(self):
        self.pattern = SimplePattern({
            ' = ': [' += ', ' -= ', ' *= ', ' /= ', ' %= '],
            ' \+= ': [' = ', ' -= ', ' *= ', ' /= ', ' %= '],
            ' -= ': [' = ', ' += ', ' *= ', ' /= ', ' %= '],
            ' \*= ': [' = ', ' += ', ' -= ', ' /= ', ' %= '],
            ' /= ': [' = ', ' += ', ' -= ', ' *= ', ' %= '],
            ' %= ': [' = ', ' += ', ' -= ', ' *= ', ' /= ']
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


class BooleanAssignmentOperatorMutator(Mutator):
    mutator_id = 'booleanAssignmentOperator'
    description = 'Replaces Boolean assignment operators.'
    tags = ['operator', 'logical']

    def __init__(self):
        self.pattern = SimplePattern({
            ' = ': [' &= ', ' |= ', ' ^= ', ' <<= ', ' >>= '],
            ' &= ': [' = ', ' |= ', ' ^= ', ' <<= ', ' >>= '],
            ' \|= ': [' = ', ' &= ', ' ^= ', ' <<= ', ' >>= '],
            ' ^= ': [' = ', ' &= ', ' |= ', ' <<= ', ' >>= '],
            ' <<= ': [' = ', ' &= ', ' |= ', ' ^= ', ' >>= '],
            ' >>= ': [' = ', ' &= ', ' |= ', ' ^= ', ' <<= ']
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


class ArithmeticOperatorMutator(Mutator):
    mutator_id = 'arithmeticOperator'
    description = 'Replaces arithmetic operators.'
    tags = ['operator', 'artithmetic']

    def __init__(self):
        self.pattern = SimplePattern({
            ' \+ ': [' - ', ' * ', ' / ', ' % '],
            ' - ': [' + ', ' * ', ' / ', ' % '],
            ' \* ': [' + ', ' - ', ' / ', ' % '],
            ' / ': [' + ', ' - ', ' * ', ' % '],
            ' % ': [' + ', ' - ', ' * ', ' / ']
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


class BooleanArithmeticOperatorMutator(Mutator):
    mutator_id = 'booleanArithmeticOperator'
    description = 'Replaces Boolean arithmetic operators.'
    tags = ['operator', 'logical']

    def __init__(self):
        self.pattern = SimplePattern({
            ' & ': [' | ', ' ^ ', ' << ', ' >> '],
            ' \| ': [' & ', ' ^ ', ' << ', ' >> '],
            ' ^ ': [' & ', ' | ', ' << ', ' >> '],
            ' << ': [' & ', ' | ', ' ^ ', ' >> '],
            ' >> ': [' & ', ' | ', ' ^ ', ' << ']
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


class BooleanLiteralMutator(Mutator):
    mutator_id = 'booleanLiteral'
    description = 'Swaps the Boolean literals true and false.'
    tags = ['logical', 'literal']

    def __init__(self):
        self.pattern = SimplePattern({
            'true': ['false'],
            'false': ['true']
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


class StdInserterMutator(Mutator):
    mutator_id = 'stdInserter'
    description = 'Changes the position where elements are inserted.'
    tags = ['stl']

    def __init__(self):
        self.pattern = SimplePattern({
            'std::front_inserter': ['std::back_inserter'],
            's#td::back_inserter': ['std::front_inserter']
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


class StdRangePredicateMutator(Mutator):
    mutator_id = 'stdRangePredicate'
    description = 'Changes the semantics of an STL range predicate.'
    tags = ['stl']

    def __init__(self):
        self.pattern = SimplePattern({
            'std::all_of': ['std::any_of', 'std::none_of'],
            'std::any_of': ['std::all_of', 'std::none_of'],
            'std::none_of': ['std::all_of', 'std::any_of']
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


class StdMinMaxMutator(Mutator):
    mutator_id = 'stdMinMax'
    description = 'Swaps STL minimum by maximum calls.'
    tags = ['stl', 'artithmetic']

    def __init__(self):
        self.pattern = SimplePattern({
            'std::min': ['std::max'],
            'std::max': ['std::min']
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


class DecimalNumberLiteralMutator(Mutator):
    mutator_id = 'decimalNumberLiteral'
    description = 'Replaces decimal number literals with different values.'
    tags = ['numerical', 'literal']

    def __init__(self):
        self.regex = r'''[^'"a-zA-Z_\\](-?[0-9]+\.?[0-9]*)[^'"a-zA-Z_]?'''

    def find_mutations(self, line):
        result = []  # type: List[Replacement]

        string_finder = StringLiteralFinder(line)

        for occurrence in [match for match in re.finditer(re.compile(self.regex), line)]:
            if string_finder.is_in_string_literal(occurrence.start()):
                continue

            number_str = occurrence.group(1)

            # use JSON as means to cope with both int and double
            try:
                number_val = json.loads(number_str)
            except ValueError:
                continue

            replacements = list({number_val + 1, number_val - 1, -number_val, 0} - {number_val})
            for replacement in replacements:
                result.append(Replacement(start_col=occurrence.start(1),
                                          end_col=occurrence.end(1),
                                          old_val=line[occurrence.start(1):occurrence.end(1)],
                                          new_val=str(replacement)))

        return result


class HexNumberLiteralMutator(Mutator):
    mutator_id = 'hexNumberLiteral'
    description = 'Replaces hex number literals with different values.'
    tags = ['numerical', 'literal']

    def __init__(self):
        self.regex = r'''0[xX][0-9A-Fa-f]+'''

    def find_mutations(self, line):
        result = []  # type: List[Replacement]

        string_finder = StringLiteralFinder(line)

        for occurrence in [match for match in re.finditer(re.compile(self.regex), line)]:
            if string_finder.is_in_string_literal(occurrence.start()):
                continue

            number_str = occurrence.group()

            # use JSON as means to cope with both int and double
            number_val = int(number_str, 0)

            replacements = list({number_val + 1, number_val - 1, -number_val, 0} - {number_val})
            for replacement in replacements:
                result.append(Replacement(start_col=occurrence.start(),
                                          end_col=occurrence.end(),
                                          old_val=line[occurrence.start():occurrence.end()],
                                          new_val=hex(replacement)))

        return result


class IteratorRangeMutator(Mutator):
    mutator_id = 'iteratorRange'
    description = 'Changes an iterator range.'
    tags = ['iterators']

    def __init__(self):
        self.pattern = SimplePattern({
            'begin\(\)': ['end()', 'begin()+1'],
            'end\(\)': ['end()-1', 'end()+1'],
            'std::begin': ['std::end'],
            'std::end': ['std::begin']
        })

    def find_mutations(self, line):
        return self.pattern.mutate(line)


def get_mutators():
    mutators = [
        LineDeletionMutator(),
        LogicalOperatorMutator(),
        ComparisonOperatorMutator(),
        IncDecOperatorMutator(),
        AssignmentOperatorMutator(),
        BooleanAssignmentOperatorMutator(),
        ArithmeticOperatorMutator(),
        BooleanArithmeticOperatorMutator(),
        BooleanLiteralMutator(),
        StdInserterMutator(),
        StdRangePredicateMutator(),
        StdMinMaxMutator(),
        DecimalNumberLiteralMutator(),
        HexNumberLiteralMutator(),
        IteratorRangeMutator()
    ]

    return {mutator.mutator_id: mutator for mutator in mutators}
