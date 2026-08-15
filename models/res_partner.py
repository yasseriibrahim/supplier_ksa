# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    default_payment_type = fields.Selection([
        ('direct', 'Direct / Immediate'), ('fixed_day', 'Fixed Day of Month'),
        ('installment', 'Period Installments'), ('credit', 'Credit Terms'),
    ], string='Default Payment Type', tracking=True)
    default_fixed_day = fields.Integer(string='Default Payment Day')
    payment_notes = fields.Text(string='Payment Behaviour Notes')

    payment_plan_count = fields.Integer(string='Payment Plans', compute='_compute_payment_plan_counts')
    active_plan_count = fields.Integer(string='Active Plans', compute='_compute_payment_plan_counts')
    overdue_installment_count = fields.Integer(string='Overdue Installments', compute='_compute_payment_plan_counts')
    total_overdue_amount = fields.Monetary(
        string='Total Overdue', compute='_compute_payment_plan_counts', currency_field='currency_id',
    )
    x_iban = fields.Char(string='IBAN')

    contract_ids = fields.One2many(
        'partner.contract', 'partner_id', string='Contracts',
    )
    contract_count = fields.Integer(
        string='Contracts', compute='_compute_contract_count',
    )

    def _compute_contract_count(self):
        Contract = self.env['partner.contract']
        for partner in self:
            partner.contract_count = Contract.search_count([('partner_id', '=', partner.id)])

    # ── Payment due near today flag (stored, refreshed by cron) ──────────
    has_payment_due_near_today = fields.Boolean(
        string='Has Payment Due Near Today',
        compute='_compute_has_payment_due_near_today',
        store=True,
    )

    @api.depends('contract_ids.installment_ids.due_date', 'contract_ids.installment_ids.state')
    def _compute_has_payment_due_near_today(self):
        from datetime import timedelta
        today = fields.Date.today()
        window_start = today - timedelta(days=1)
        window_end = today + timedelta(days=1)
        Installment = self.env['partner.payment.installment']
        for partner in self:
            count = Installment.search_count([
                ('partner_id', '=', partner.id),
                ('contract_id', '!=', False),
                ('due_date', '>=', window_start),
                ('due_date', '<=', window_end),
                ('state', 'not in', ['paid', 'waived']),
            ])
            partner.has_payment_due_near_today = bool(count)

    @api.model
    def _cron_refresh_payment_due_flag(self):
        """Called daily by cron to refresh the stored flag for all customers."""
        partners = self.search([('customer_rank', '>', 0)])
        partners._compute_has_payment_due_near_today()

    def action_view_contracts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contracts — %s') % self.name,
            'res_model': 'partner.contract',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def _compute_payment_plan_counts(self):
        Plan = self.env['partner.payment.profile']
        Installment = self.env['partner.payment.installment']
        for partner in self:
            plans = Plan.search([('partner_id', '=', partner.id)])
            partner.payment_plan_count = len(plans)
            partner.active_plan_count = len(plans.filtered(lambda p: p.state == 'active'))
            overdue_lines = Installment.search([
                ('partner_id', '=', partner.id),
                ('is_overdue', '=', True),
                ('state', 'not in', ['paid', 'waived']),
            ])
            partner.overdue_installment_count = len(overdue_lines)
            partner.total_overdue_amount = sum(overdue_lines.mapped('amount_remaining'))

    def action_view_payment_plans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payment Plans — %s') % self.name,
            'res_model': 'partner.payment.profile',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for partner in records:
            if not partner.is_company:
                partner._set_default_accounts()
        return records

    def _set_default_accounts(self):
        """Set default receivable/payable accounts for individual partners."""
        company = self.env.company
        AccountAccount = self.env['account.account']

        if not self.property_account_receivable_id:
            receivable = AccountAccount.search([
                ('account_type', '=', 'asset_receivable'),
                ('company_ids', 'in', company.id),
            ], limit=1)
            if receivable:
                self.property_account_receivable_id = receivable

        if not self.property_account_payable_id:
            payable = AccountAccount.search([
                ('account_type', '=', 'liability_payable'),
                ('company_ids', 'in', company.id),
            ], limit=1)
            if payable:
                self.property_account_payable_id = payable

    def action_view_overdue_installments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Overdue Installments — %s') % self.name,
            'res_model': 'partner.payment.installment',
            'view_mode': 'list,form',
            'domain': [
                ('partner_id', '=', self.id),
                ('is_overdue', '=', True),
                ('state', 'not in', ['paid', 'waived']),
            ],
        }

