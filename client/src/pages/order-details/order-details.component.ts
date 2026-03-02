// client/src/pages/order-details/order-details.component.ts
import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { OrdersService, OrderOut } from '../../services/orders.service';

@Component({
  standalone: true,
  selector: 'app-order-details',
  imports: [CommonModule, RouterLink],
  templateUrl: './order-details.component.html'
})
export class OrderDetailsComponent implements OnInit {
  order?: OrderOut;
  loading = true;
  error = '';
  copied = false;

  constructor(private route: ActivatedRoute, private svc: OrdersService) {}

  ngOnInit() {
    const id = Number(this.route.snapshot.paramMap.get('orderId'));
    this.svc.get(id).subscribe({
      next: (o) => { this.order = o; this.loading = false; },
      error: (err) => { this.error = err?.error?.detail || 'Failed to load order'; this.loading = false; }
    });
  }

  total(o: OrderOut) { return `₹${(o.total_amount_cents/100).toFixed(2)}`; }

  statusClass(status: OrderOut['status']): string {
    switch (status) {
      case 'PAID': return 'badge badge--ok';
      case 'PENDING_PAYMENT': return 'badge badge--warn';
      case 'CANCELLED': return 'badge badge--err';
      default: return 'badge';
    }
  }

  async copy(id: number) {
    try {
      await navigator.clipboard.writeText(String(id));
      this.copied = true;
      setTimeout(() => (this.copied = false), 1200);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = String(id);
      document.body.appendChild(ta);
      ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
      this.copied = true;
      setTimeout(() => (this.copied = false), 1200);
    }
  }
}