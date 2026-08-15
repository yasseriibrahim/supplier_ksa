# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta


class PartnerContract(models.Model):
    _name = 'partner.contract'
    _description = 'Partner Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'partner_id, start_date desc'

    name = fields.Char(
        string='Contract Reference', required=True, copy=False,
        readonly=True, default=lambda self: _('New'), tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True,
        ondelete='cascade', index=True, tracking=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('renewed', 'Renewed'),
        ('done', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, copy=False)

    start_date = fields.Date(
        string='Contract Start Date', required=True,
        default=fields.Date.context_today, tracking=True,
    )
    end_date = fields.Date(
        string='Contract End Date', tracking=True,
    )
    contract_amount = fields.Monetary(
        string='Contract Amount', required=True,
        currency_field='currency_id', tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    payment_periods = fields.Selection([
        ('25', '25%  — Quarterly  (4 installments)'),
        ('50', '50%  — Semi-Annual (2 installments)'),
        ('100', '100% — Annual     (1 installment)'),
    ], string='Payment Periods', tracking=True)

    installment_ids = fields.One2many(
        'partner.payment.installment', 'contract_id',
        string='Installment Schedule',
    )
    installment_count = fields.Integer(
        string='Installments', compute='_compute_installment_count',
    )

    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
    )
    notes = fields.Text(string='Notes')
    auto_renew = fields.Boolean(
        string='Automatic Yearly Renewal', default=True, tracking=True,
        help='Create a new contract with the same values and payment schedule when this contract expires.',
    )
    previous_contract_id = fields.Many2one(
        'partner.contract', string='Previous Contract', copy=False,
        readonly=True, ondelete='set null', index=True,
    )
    renewed_contract_id = fields.Many2one(
        'partner.contract', string='Renewed Contract', copy=False,
        readonly=True, ondelete='set null', index=True,
    )

    # ── Computed summary fields ────────────────────────────────────────────
    amount_paid = fields.Monetary(
        string='Amount Paid', compute='_compute_amounts',
        store=True, currency_field='currency_id',
    )
    amount_remaining = fields.Monetary(
        string='Remaining', compute='_compute_amounts',
        store=True, currency_field='currency_id',
    )
    next_payment_date = fields.Date(
        string='Next Payment Date', compute='_compute_next_payment_date',
        store=True,
    )

    # ── ORM ───────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('partner.contract') or _('New')
                )
        return super().create(vals_list)

    # ── Default end_date: start_date + 1 year ────────────────────────────
    @api.onchange('start_date')
    def _onchange_start_date(self):
        if self.start_date:
            self.end_date = self.start_date + relativedelta(years=1)

    # ── Auto-generate installment lines when all required fields are set ──
    @api.onchange('start_date', 'contract_amount', 'payment_periods')
    def _onchange_generate_preview(self):
        """Refresh the installment schedule in the form whenever key fields change."""
        if self.start_date and self.contract_amount and self.payment_periods:
            self._generate_installment_lines(preview=True)

    # ── Computes ──────────────────────────────────────────────────────────
    @api.depends('installment_ids')
    def _compute_installment_count(self):
        for rec in self:
            rec.installment_count = len(rec.installment_ids)

    @api.depends('installment_ids.amount_paid', 'installment_ids.amount_expected', 'contract_amount')
    def _compute_amounts(self):
        for rec in self:
            paid = sum(rec.installment_ids.mapped('amount_paid'))
            rec.amount_paid = paid
            rec.amount_remaining = max(0.0, rec.contract_amount - paid)

    @api.depends('installment_ids.due_date', 'installment_ids.state')
    def _compute_next_payment_date(self):
        today = fields.Date.today()
        for rec in self:
            pending = rec.installment_ids.filtered(
                lambda l: l.state not in ('paid', 'waived') and l.due_date and l.due_date >= today
            ).sorted('due_date')
            rec.next_payment_date = pending[0].due_date if pending else False

    # ── Installment generation logic ──────────────────────────────────────
    def _get_installment_schedule(self):
        """Return list of (sequence, due_date, amount) tuples based on payment_periods."""
        self.ensure_one()
        periods = int(self.payment_periods)           # 25 → 4,  50 → 2,  100 → 1
        count = 100 // periods                        # number of installments
        amount_each = self.contract_amount / count
        interval_months = 12 // count                 # months between installments

        schedule = []
        for i in range(count):
            # Advance payment: first installment on start_date (i=0 → offset 0),
            # then one period ahead for each subsequent installment.
            due = self.start_date + relativedelta(months=interval_months * i)
            # Clamp to end_date if set
            if self.end_date and due > self.end_date:
                due = self.end_date
            schedule.append((i + 1, due, amount_each))
        return schedule

    def _generate_installment_lines(self, preview=False):
        """
        Delete existing draft installment lines for this contract and
        recreate them from the current schedule.
        If preview=True we are inside an onchange — use virtual records only.
        """
        self.ensure_one()
        if not (self.start_date and self.contract_amount and self.payment_periods):
            return

        schedule = self._get_installment_schedule()

        if preview:
            # In onchange context we cannot write to DB; replace the O2M cache
            new_lines = []
            for seq, due, amount in schedule:
                new_lines.append((0, 0, {
                    'sequence': seq,
                    'due_date': due,
                    'amount_expected': amount,
                    'amount_paid': 0.0,
                    'state': 'pending',
                }))
            # Remove virtual lines first, then add new ones
            self.installment_ids = [(5, 0, 0)] + new_lines
        else:
            # Real write — remove only lines that are still pending/draft
            existing_draft = self.installment_ids.filtered(
                lambda l: l.state in ('pending',)
            )
            existing_draft.unlink()
            vals_list = []
            for seq, due, amount in schedule:
                vals_list.append({
                    'contract_id': self.id,
                    'partner_id': self.partner_id.id,
                    'sequence': seq,
                    'due_date': due,
                    'amount_expected': amount,
                    'amount_paid': 0.0,
                    'state': 'pending',
                })
            self.env['partner.payment.installment'].create(vals_list)

    # ── Actions ───────────────────────────────────────────────────────────
    def action_generate_installments(self):
        """Button: (re)generate installment lines from current settings."""
        for rec in self:
            rec._generate_installment_lines(preview=False)

    def action_activate(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError(_('Only draft contracts can be activated.'))
            if not rec.installment_ids:
                raise ValidationError(_('Generate installment lines before activating.'))
            rec.write({'state': 'active'})

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise ValidationError(_('Completed contracts cannot be cancelled.'))
            rec.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_mark_done(self):
        for rec in self:
            if rec.amount_remaining > 0.01:
                raise ValidationError(
                    _('Cannot complete contract "%s": remaining balance is %.2f.')
                    % (rec.name, rec.amount_remaining)
                )
            rec.write({'state': 'done'})

    def action_renew_contract(self):
        """Create the next yearly contract with an identical annual schedule."""
        renewed = self.env['partner.contract']
        for rec in self:
            if rec.renewed_contract_id:
                renewed |= rec.renewed_contract_id
                continue
            if rec.state not in ('active', 'done'):
                raise ValidationError(_('Only active or completed contracts can be renewed.'))
            if not rec.start_date:
                raise ValidationError(_('A start date is required to renew the contract.'))

            next_start = rec.start_date + relativedelta(years=1)
            next_end = (rec.end_date + relativedelta(years=1)) if rec.end_date else (
                next_start + relativedelta(years=1)
            )
            new_contract = self.create({
                'partner_id': rec.partner_id.id,
                'state': 'draft',
                'start_date': next_start,
                'end_date': next_end,
                'contract_amount': rec.contract_amount,
                'currency_id': rec.currency_id.id,
                'payment_periods': rec.payment_periods,
                'company_id': rec.company_id.id,
                'notes': rec.notes,
                'auto_renew': rec.auto_renew,
                'previous_contract_id': rec.id,
            })
            new_contract._generate_installment_lines(preview=False)
            new_contract.write({'state': 'active'})
            rec.write({
                'state': 'renewed',
                'renewed_contract_id': new_contract.id,
            })
            renewed |= new_contract
        if len(self) == 1 and renewed:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Renewed Contract'),
                'res_model': 'partner.contract',
                'view_mode': 'form',
                'res_id': renewed.id,
                'target': 'current',
            }
        return True

    @api.model
    def _cron_renew_yearly_contracts(self):
        """Renew every expired contract, including missed years after downtime."""
        today = fields.Date.today()
        while True:
            expired = self.search([
                ('state', '=', 'active'),
                ('auto_renew', '=', True),
                ('end_date', '!=', False),
                ('end_date', '<=', today),
                ('renewed_contract_id', '=', False),
            ], limit=100)
            if not expired:
                break
            expired.action_renew_contract()
        return True

    # ── Constraints ───────────────────────────────────────────────────────
    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date <= rec.start_date:
                raise ValidationError(_('End date must be after start date.'))

    @api.constrains('contract_amount')
    def _check_amount(self):
        for rec in self:
            if rec.contract_amount <= 0:
                raise ValidationError(_('Contract amount must be positive.'))
