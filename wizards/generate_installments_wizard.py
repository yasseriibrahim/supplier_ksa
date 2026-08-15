# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta
from datetime import timedelta


class PartnerPaymentGenerateWizard(models.TransientModel):
    _name = 'partner.payment.generate.wizard'
    _description = 'Generate Installment Lines'

    plan_id = fields.Many2one('partner.payment.profile', string='Payment Plan', required=True, readonly=True)
    partner_id = fields.Many2one(related='plan_id.partner_id', string='Client', readonly=True)
    total_amount = fields.Monetary(related='plan_id.total_amount', string='Total Amount', readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='plan_id.currency_id')

    installment_count = fields.Integer(string='Number of Installments', required=True, default=1)
    frequency = fields.Selection([
        ('weekly', 'Weekly'), ('biweekly', 'Bi-Weekly'), ('monthly', 'Monthly'),
        ('bimonthly', 'Every 2 Months'), ('quarterly', 'Quarterly'), ('custom', 'Custom (N days)'),
    ], string='Frequency', required=True, default='monthly')
    custom_days = fields.Integer(string='Every N Days', default=30)
    start_date = fields.Date(string='First Payment Date', required=True, default=fields.Date.context_today)
    bank_id = fields.Many2one('res.partner.bank', string='Bank Account',
        domain="[('partner_id', '=', partner_id)]")
    amount_per_installment = fields.Monetary(
        string='Amount per Installment', compute='_compute_amount_per', store=True, currency_field='currency_id',
    )
    last_installment_adjustment = fields.Monetary(
        string='Last Installment (adjusted)', compute='_compute_amount_per', store=True, currency_field='currency_id',
    )
    preview_line_ids = fields.One2many(
        'partner.payment.generate.wizard.preview', 'wizard_id', string='Preview', compute='_compute_preview',
    )

    @api.depends('total_amount', 'installment_count')
    def _compute_amount_per(self):
        for wiz in self:
            if wiz.installment_count and wiz.installment_count > 0 and wiz.total_amount:
                base = round(wiz.total_amount / wiz.installment_count, 2)
                last = round(wiz.total_amount - base * (wiz.installment_count - 1), 2)
                wiz.amount_per_installment = base
                wiz.last_installment_adjustment = last
            else:
                wiz.amount_per_installment = wiz.total_amount
                wiz.last_installment_adjustment = wiz.total_amount

    @api.depends('installment_count', 'frequency', 'start_date',
                 'amount_per_installment', 'last_installment_adjustment', 'custom_days')
    def _compute_preview(self):
        for wiz in self:
            wiz.preview_line_ids = [(5, 0, 0)]
            if not wiz.start_date or not wiz.installment_count:
                continue
            lines = []
            current_date = wiz.start_date
            for i in range(wiz.installment_count):
                amount = wiz.last_installment_adjustment if i == wiz.installment_count - 1 else wiz.amount_per_installment
                lines.append((0, 0, {'sequence': i + 1, 'due_date': current_date, 'amount_expected': amount}))
                current_date = wiz._next_date(current_date)
            wiz.preview_line_ids = lines

    def _next_date(self, current):
        freq = self.frequency
        if freq == 'weekly':
            return current + timedelta(weeks=1)
        elif freq == 'biweekly':
            return current + timedelta(weeks=2)
        elif freq == 'monthly':
            return current + relativedelta(months=1)
        elif freq == 'bimonthly':
            return current + relativedelta(months=2)
        elif freq == 'quarterly':
            return current + relativedelta(months=3)
        else:
            return current + timedelta(days=self.custom_days or 30)

    def action_generate(self):
        self.ensure_one()
        plan = self.plan_id
        if plan.state not in ('draft', 'active'):
            raise UserError(_('Can only generate lines for Draft or Active plans.'))
        removable = plan.installment_line_ids.filtered(lambda l: l.state in ('pending', 'overdue'))
        removable.unlink()
        existing_paid = plan.installment_line_ids.filtered(lambda l: l.state in ('paid', 'waived', 'partial'))
        seq_start = len(existing_paid) + 1
        current_date = self.start_date
        lines_vals = []
        for i in range(self.installment_count):
            amount = self.last_installment_adjustment if i == self.installment_count - 1 else self.amount_per_installment
            lines_vals.append({
                'plan_id': plan.id, 'sequence': seq_start + i,
                'due_date': current_date, 'amount_expected': amount, 'state': 'pending',
                'bank_id': self.bank_id.id if self.bank_id else False,
            })
            current_date = self._next_date(current_date)
        self.env['partner.payment.installment'].create(lines_vals)
        plan.write({
            'installment_count': self.installment_count,
            'installment_frequency': self.frequency,
            'start_date': self.start_date,
            'custom_days': self.custom_days,
        })
        return {'type': 'ir.actions.act_window_close'}


class PartnerPaymentGenerateWizardPreview(models.TransientModel):
    _name = 'partner.payment.generate.wizard.preview'
    _description = 'Installment Preview Line'
    _order = 'sequence'

    wizard_id = fields.Many2one('partner.payment.generate.wizard', ondelete='cascade')
    sequence = fields.Integer(string='#')
    due_date = fields.Date(string='Due Date')
    amount_expected = fields.Monetary(string='Amount', currency_field='currency_id')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
