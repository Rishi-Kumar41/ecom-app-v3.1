import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { OrdersService, OrderOut } from '../../services/orders.service';
import { CartService } from '../../services/cart.service';

@Component({
  standalone: true,
  selector: 'app-payment',
  imports: [CommonModule],
  templateUrl: './payment.component.html'
})
export class PaymentComponent implements OnInit {
  orderId!: number;
  order?: OrderOut;    
  status = 'PENDING_PAYMENT';
  message = '';
  loading = false;

  constructor(
    private route: ActivatedRoute,
    private orders: OrdersService,
    private router: Router,
    private cart: CartService
  ) {}

  ngOnInit() {
    this.orderId = Number(this.route.snapshot.paramMap.get('orderId'));
    if (this.orderId) {
      this.orders.get(this.orderId).subscribe({
        next: (o) => {
          this.order = o;
          this.status = o.status;
        },
        error: () => {
          this.message = 'Failed to load order';
        }
      });
    }
  }

  payNow() {
    if (!this.orderId) return;

    this.loading = true;
    this.orders.pay(this.orderId).subscribe({
      next: (res) => {
        // Redirect to Stripe checkout
        window.location.href = res.checkout_url;
      },
      error: () => {
        this.message = 'Failed to start payment';
        this.loading = false;
      }
    });
  }

  goOrders() {
    this.router.navigateByUrl('/orders');
  }
}