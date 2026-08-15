# -*- coding: utf-8 -*-
import io
from odoo import models, _


class PartnerLedgerReportHandlerExt(models.AbstractModel):
    _name = 'supplier_ksa.partner.ledger.report.handler'
    _inherit = 'account.partner.ledger.report.handler'
    _description = 'Partner Ledger Report Handler – Account Statement Extension'

    def _custom_options_initializer(self, report, options, previous_options):
        super()._custom_options_initializer(report, options, previous_options)

        # Add the "Print Account Statement" button next to the standard PDF button.
        options['buttons'].append({
            'name': _('Print Account Statement'),
            'sequence': 15,
            'action': 'export_file',
            'action_param': 'action_print_account_statement',
            'file_export_type': _('PDF'),
            'branch_allowed': True,
            'always_show': True,
        })

        # When this handler is active AND we're in account-statement mode,
        # swap the PDF export template.  We use a flag in previous_options so
        # that the swap only happens during our own print call, not the regular
        # PDF button.
        if previous_options.get('_account_statement_mode'):
            options.setdefault('custom_display_config', {}) \
                   .setdefault('pdf_export', {})['pdf_export_main'] = \
                'supplier_ksa.account_statement_pdf_main'

    def action_print_account_statement(self, options):
        """
        Print a styled bilingual Account Statement PDF.
        Produces the same data as the standard PDF button but uses our custom
        QWeb template (styled table + company logo + client-name header).
        All active date/partner filters are respected.
        """
        report = self.env['account.report'].browse(options['report_id'])

        # Re-build options for print mode, injecting our flag so that
        # _custom_options_initializer picks up the template swap.
        base_options = {**options, 'export_mode': 'print', '_account_statement_mode': True}
        print_options = report.get_options(previous_options=base_options)

        # Determine which reports to print (handles sectioned reports).
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
        rcontext = {'mode': 'print', 'base_url': base_url, 'company': self.env.company}

        reports_options = []
        for rpt in reports_to_print:
            rpt_options = rpt.get_options(
                previous_options={**print_options, 'selected_section_id': rpt.id,
                                  '_account_statement_mode': True}
            )
            reports_options.append(rpt_options)

        from itertools import groupby
        grouped = groupby(
            zip(reports_to_print, reports_options),
            key=lambda x: len(x[1]['columns']) > 5 or x[1].get('horizontal_split'),
        )

        action_report = self.env['ir.actions.report']
        footer = report._get_layout_footer(rcontext)
        files_stream = []
        for is_landscape, items in grouped:
            bodies = (
                rpt._get_pdf_export_html(
                    rpt_opts,
                    rpt._filter_out_folded_children(rpt._get_lines(rpt_opts)),
                    additional_context={'base_url': base_url},
                )
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
