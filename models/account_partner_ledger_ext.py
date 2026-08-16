# -*- coding: utf-8 -*-
import io
from odoo import models, _


class PartnerLedgerReportHandlerExt(models.AbstractModel):
    _name = 'supplier_ksa.partner.ledger.report.handler'
    _inherit = 'account.partner.ledger.report.handler'
    _description = 'Partner Ledger Report Handler – Account Statement Extension'

    # ------------------------------------------------------------------ #
    #  Options initializer – adds button + swaps template when needed      #
    # ------------------------------------------------------------------ #

    def _custom_options_initializer(self, report, options, previous_options):
        super()._custom_options_initializer(report, options, previous_options)

        options['buttons'].append({
            'name': _('Print Account Statement'),
            'sequence': 15,
            'action': 'export_file',
            'action_param': 'action_print_account_statement',
            'file_export_type': _('PDF'),
            'branch_allowed': True,
            'always_show': True,
        })

        if previous_options.get('_account_statement_mode'):
            options.setdefault('custom_display_config', {}) \
                   .setdefault('pdf_export', {})['pdf_export_main'] = \
                'supplier_ksa.account_statement_pdf_main'

    # ------------------------------------------------------------------ #
    #  Main print action                                                   #
    # ------------------------------------------------------------------ #

    def action_print_account_statement(self, options):
        """Print a styled bilingual Account Statement PDF."""
        report = self.env['account.report'].browse(options['report_id'])

        # unfold_all=True is critical – without it _get_lines returns only
        # partner header lines (level=0) and _filter_out_folded_children
        # removes every child, producing an empty report.
        base_options = {
            **options,
            'export_mode': 'print',
            'unfold_all': True,
            '_account_statement_mode': True,
        }
        print_options = report.get_options(previous_options=base_options)

        if print_options.get('sections'):
            reports_to_print = self.env['account.report'].browse(
                [s['id'] for s in print_options['sections']]
            )
        else:
            reports_to_print = report

        base_url = (
            self.env['ir.config_parameter'].sudo().get_param('report.url') or
            self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        )
        rcontext = {
            'mode': 'print',
            'base_url': base_url,
            'company': self.env.company,
        }

        reports_options = []
        for rpt in reports_to_print:
            rpt_options = rpt.get_options(
                previous_options={
                    **print_options,
                    'selected_section_id': rpt.id,
                    'unfold_all': True,
                    '_account_statement_mode': True,
                }
            )
            reports_options.append(rpt_options)

        from itertools import groupby as itr_groupby
        grouped = itr_groupby(
            zip(reports_to_print, reports_options),
            key=lambda x: len(x[1]['columns']) > 5 or x[1].get('horizontal_split'),
        )

        action_report = self.env['ir.actions.report']
        footer = report._get_layout_footer(rcontext)
        files_stream = []

        for is_landscape, items in grouped:
            bodies = (
                self._get_account_statement_html(rpt, rpt_opts, base_url)
                for rpt, rpt_opts in items
            )
            files_stream.append(
                io.BytesIO(action_report._run_wkhtmltopdf(
                    bodies,
                    footer=footer,
                    landscape=is_landscape or self.env.context.get('force_landscape_printing'),
                    specific_paperformat_args={
                        'data-report-margin-top': 10,
                        'data-report-header-spacing': 10,
                        'data-report-margin-bottom': 15,
                    },
                ))
            )

        if len(files_stream) > 1:
            result_stream = action_report._merge_pdfs(files_stream)
            result = result_stream.getvalue()
            result_stream.close()
            for fs in files_stream:
                fs.close()
        else:
            result = files_stream[0].read()
            files_stream[0].close()

        return {
            'file_name': report.get_default_report_filename(options, 'pdf'),
            'file_content': result,
            'file_type': 'pdf',
        }

    # ------------------------------------------------------------------ #
    #  HTML rendering – groups flat lines into per-partner sections        #
    # ------------------------------------------------------------------ #

    def _get_account_statement_html(self, report, options, base_url):
        """
        Fetch all lines (with unfold_all already True in options),
        group them by partner, and render via our custom QWeb template.

        Line structure produced by _get_lines when unfold_all=True:
          level=0, 'total' NOT in id  → partner header (has summary columns)
          level>0                      → transaction detail rows
          level=0, 'total' IN id       → grand total
        """
        # _get_lines already expands everything because options['unfold_all']=True
        raw_lines = report._get_lines(options)

        partners = []       # [{header: line_dict, rows: [line_dict, ...]}, ...]
        grand_total = None
        current = None

        for line in raw_lines:
            level   = line.get('level', 0)
            line_id = str(line.get('id', ''))
            is_total = 'total' in line_id

            if level == 0 and not is_total:
                current = {'header': line, 'rows': []}
                partners.append(current)
            elif level > 0 and not is_total:
                if current is not None:
                    current['rows'].append(line)
            elif level == 0 and is_total:
                grand_total = line

        render_values = {
            'report':      report,
            'options':     options,
            'partners':    partners,
            'grand_total': grand_total,
            'base_url':    base_url,
            'env':         self.env,
        }

        return self.env['ir.qweb']._render(
            'supplier_ksa.account_statement_pdf_main',
            render_values,
        )
