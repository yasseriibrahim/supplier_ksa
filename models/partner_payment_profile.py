# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
from datetime import date


class PartnerPaymentProfile(models.Model):
    _name = 'partner.payment.profile'
    _description = 'Partner Payment Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'partner_id, start_date desc'

    name = fields.Char(
        string='Plan Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New'), tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Client', required=True, ondelete='cascade', index=True, tracking=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'), ('active', 'Active'), ('done', 'Completed'), ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, copy=False)

    payment_type = fields.Selection([
        ('direct', 'Direct / Immediate'), ('fixed_day', 'Fixed Day of Month'),
        ('installment', 'Period Installments'), ('credit', 'Credit Terms'),
    ], string='Payment Type', required=True, default='direct', tracking=True)

    fixed_day = fields.Integer(string='Payment Day')
    credit_limit = fields.Monetary(string='Credit Limit', currency_field='currency_id')
    grace_days = fields.Integer(string='Grace Days')

    invoice_id = fields.Many2one('account.move', string='Linked Invoice', tracking=True)
    invoice_id_domain = fields.Char(compute='_compute_invoice_id_domain')

    @api.depends('partner_id')
    def _compute_invoice_id_domain(self):
        for plan in self:
            if plan.partner_id:
                plan.invoice_id_domain = str([
                    ('partner_id', '=', plan.partner_id.id),
                    ('move_type', 'in', ['out_invoice', 'out_refund']),
                    ('state', '=', 'posted'),
                ])
            else:
                plan.invoice_id_domain = str([
                    ('move_type', 'in', ['out_invoice', 'out_refund']), ('state', '=', 'posted'),
                ])

    invoice_amount_total = fields.Monetary(
        related='invoice_id.amount_total', string='Invoice Total', currency_field='currency_id', readonly=True,
    )
    invoice_state = fields.Selection(
        related='invoice_id.payment_state', string='Invoice Payment State', readonly=True,
    )

    total_amount = fields.Monetary(
        string='Total Plan Amount', required=True, currency_field='currency_id', tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency', default=lambda self: self.env.company.currency_id,
    )
    amount_paid = fields.Monetary(
        string='Amount Paid', compute='_compute_amounts', store=True, currency_field='currency_id',
    )
    amount_remaining = fields.Monetary(
        string='Remaining Balance', compute='_compute_amounts', store=True, currency_field='currency_id',
    )
    amount_overdue = fields.Monetary(
        string='Overdue Amount', compute='_compute_amounts', store=True, currency_field='currency_id',
    )
    progress_pct = fields.Float(
        string='Collection %', compute='_compute_amounts', store=True, digits=(5, 1),
    )

    installment_count = fields.Integer(string='Number of Installments', default=1)
    installment_frequency = fields.Selection([
        ('weekly', 'Weekly'), ('biweekly', 'Bi-Weekly'), ('monthly', 'Monthly'),
        ('bimonthly', 'Every 2 Months'), ('quarterly', 'Quarterly'), ('custom', 'Custom'),
    ], string='Frequency', default='monthly')
    custom_days = fields.Integer(string='Every N Days', default=30)
    start_date = fields.Date(string='First Payment Date', default=fields.Date.context_today, tracking=True)
    amount_per_installment = fields.Monetary(
        string='Amount per Installment', compute='_compute_amount_per_installment',
        store=True, currency_field='currency_id',
    )

    installment_line_ids = fields.One2many(
        'partner.payment.installment', 'plan_id', string='Installment Lines',
    )
    notes = fields.Text(string='Internal Notes')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('partner.payment.profile') or _('New')
        return super().create(vals_list)

    @api.depends('installment_line_ids.amount_paid', 'installment_line_ids.amount_expected',
                 'installment_line_ids.state', 'total_amount')
    def _compute_amounts(self):
        today = date.today()
        for plan in self:
            paid = sum(plan.installment_line_ids.mapped('amount_paid'))
            overdue = sum(
                line.amount_expected - line.amount_paid
                for line in plan.installment_line_ids
                if line.state in ('overdue', 'partial') and line.due_date and line.due_date < today
            )
            plan.amount_paid = paid
            plan.amount_remaining = max(0.0, plan.total_amount - paid)
            plan.amount_overdue = max(0.0, overdue)
            plan.progress_pct = (paid / plan.total_amount * 100) if plan.total_amount else 0.0

    @api.depends('total_amount', 'installment_count')
    def _compute_amount_per_installment(self):
        for plan in self:
            if plan.installment_count and plan.installment_count > 0:
                plan.amount_per_installment = plan.total_amount / plan.installment_count
            else:
                plan.amount_per_installment = plan.total_amount

    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        if self.invoice_id:
            self.total_amount = self.invoice_id.amount_total
            self.currency_id = self.invoice_id.currency_id

    @api.onchange('payment_type')
    def _onchange_payment_type(self):
        if self.payment_type == 'direct':
            self.installment_count = 1
            self.installment_frequency = 'monthly'
        elif self.payment_type == 'fixed_day':
            self.installment_count = 1

    def action_activate(self):
        for plan in self:
            if plan.state != 'draft':
                raise UserError(_('Only draft plans can be activated.'))
            if not plan.installment_line_ids:
                raise UserError(_('Generate installment lines before activating the plan.'))
            plan.write({'state': 'active'})

    def action_mark_done(self):
        for plan in self:
            if plan.amount_remaining > 0.01:
                raise UserError(_('Cannot complete plan "%s": remaining balance is %s.') % (
                    plan.name, plan.amount_remaining))
            plan.write({'state': 'done'})

    def action_cancel(self):
        for plan in self:
            if plan.state == 'done':
                raise UserError(_('Completed plans cannot be cancelled.'))
            plan.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_generate_installments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Installments'),
            'res_model': 'partner.payment.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_plan_id': self.id,
                'default_installment_count': self.installment_count,
                'default_start_date': str(self.start_date or fields.Date.today()),
                'default_frequency': self.installment_frequency,
                'default_amount_per_installment': self.amount_per_installment,
                'default_custom_days': self.custom_days,
            },
        }

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return
        return {'type': 'ir.actions.act_window', 'name': _('Invoice'),
                'res_model': 'account.move', 'view_mode': 'form', 'res_id': self.invoice_id.id}

    @api.constrains('fixed_day')
    def _check_fixed_day(self):
        for plan in self:
            if plan.payment_type == 'fixed_day' and plan.fixed_day:
                if not (1 <= plan.fixed_day <= 28):
                    raise ValidationError(_('Payment day must be between 1 and 28.'))

    @api.constrains('installment_count')
    def _check_installment_count(self):
        for plan in self:
            if plan.installment_count < 1:
                raise ValidationError(_('Number of installments must be at least 1.'))
