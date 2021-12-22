#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import json
import sys
from ipaperftest.core.plugin import Registry


class OutputRegistry(Registry):
    pass


output_registry = OutputRegistry()


class Output:
    """Base class for writing/displaying the output of results

       options is a tuple of argparse options that can add
       class-specific options for output.

       Output will be typically generated like:
       >>> output = JSON(options)
       >>> output.render(results)

       render() will:
       2. Generate a string to be written (generate)
       3. Write to the requested file or stdout (write_file)

       stdout == sys.stdout by default.

       An Output class only needs to implement the generate() method
       which will render the results into a string for writing.
    """
    def __init__(self, outputfile=None):
        self.filename = outputfile

    def render(self, results):
        """Process the results into output"""
        data = [line for line in results.output()]
        output = self.generate(data)
        self.write_file(output)

    def write_file(self, output):
        """Write the output to a file or sys.stdout"""
        if self.filename:
            with open(self.filename, 'w') as fd:
                fd.write(output)
        else:
            sys.stdout.write(output)

    def generate(self, data):
        """Convert the output to the desired format, ready for writing

           This is the only method an output plugin is required to
           provide. The return value should be in ready-to-write format.

           Returns a string.
        """
        raise NotImplementedError


@output_registry
class JSON(Output):
    """Output information in JSON format"""

    def __init__(self, outputfile=None):
        super().__init__(outputfile)

    def generate(self, data):
        output = json.dumps(data)
        if self.filename is None:
            output += '\n'

        return output


@output_registry
class Human(Output):
    """Display output in a more human-friendly way"""

    def __init__(self, outputfile=None):
        super().__init__(outputfile)

    def generate(self, data):
        if not data:
            return "No issues found.\n"
        output = ''
        for line in data:
            kw = line.get('kw')
            result = line.get('result')
            source = line.get('source')
            test = line.get('test')
            outline = '%s: %s.%s' % (result, source, test)
            if 'key' in kw:
                outline += '.%s' % kw.get('key')
            if 'msg' in kw:
                msg = kw.get('msg')
                err = msg.format(**kw)
                outline += ': %s' % err
            elif 'exception' in kw:
                outline += ': %s' % kw.get('exception')
            output += outline + '\n'

        return output
