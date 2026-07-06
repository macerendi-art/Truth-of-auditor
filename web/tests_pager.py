from django.core.paginator import Paginator
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase

from web.templatetags.web_extras import pager


class PagerTagTests(SimpleTestCase):
    def _page(self, total, per, number):
        return Paginator(list(range(total)), per).get_page(number)

    def test_base_qs_preserves_filters_but_drops_page(self):
        req = RequestFactory().get("/x?bucket=tidak_cocok&bank=BCA&page=3&sort=amount")
        ctx = pager({"request": req}, self._page(4000, 40, 3))
        self.assertIn("bucket=tidak_cocok", ctx["base_qs"])
        self.assertIn("bank=BCA", ctx["base_qs"])
        self.assertIn("sort=amount", ctx["base_qs"])
        self.assertNotIn("page=", ctx["base_qs"])

    def test_elided_window_has_ellipsis_and_neighbors(self):
        req = RequestFactory().get("/x")
        ctx = pager({"request": req}, self._page(4000, 40, 50))  # 100 halaman, aktif 50
        nums = ctx["nums"]
        self.assertIn(ctx["ellipsis"], nums)
        for n in range(46, 55):
            self.assertIn(n, nums)
        self.assertIn(1, nums)
        self.assertIn(100, nums)

    def test_render_marks_current_and_keeps_filter_on_links(self):
        req = RequestFactory().get("/x?bucket=cocok")
        page = self._page(4000, 40, 50)
        html = Template("{% load web_extras %}{% pager page %}").render(
            Context({"page": page, "request": req})
        )
        self.assertIn('aria-current="page"', html)
        self.assertIn("Navigasi halaman", html)
        self.assertIn("page=49", html)  # link tetangga ada
        self.assertIn("bucket=cocok", html)  # filter dipertahankan di href

    def test_single_page_renders_nothing(self):
        req = RequestFactory().get("/x")
        html = Template("{% load web_extras %}{% pager page %}").render(
            Context({"page": self._page(10, 40, 1), "request": req})
        )
        self.assertNotIn("Navigasi halaman", html)
