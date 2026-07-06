from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class ValidateBrandsCommandTests(TestCase):
    def test_command_ada_dan_butuh_dir(self):
        out = StringIO()
        # tanpa --dir → command harus error argumen (CommandError, bukan crash import)
        with self.assertRaises(CommandError):
            call_command("validate_brands", stderr=out)

    def test_report_format_helper(self):
        from reconciliation.management.commands.validate_brands import format_rate

        self.assertEqual(format_rate(95, 100), "95/100 (95.0%)")
        self.assertEqual(format_rate(0, 0), "0/0 (n/a)")
