import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { OrdersService } from '../../services/orders.service';
import { CartService } from '../../services/cart.service';

@Component({ standalone: true, selector: 'app-payment', imports: [CommonModule], templateUrl: './payment.component.html' })
export class PaymentComponent implements OnInit { orderId!: number; status = 'PENDING_PAYMENT'; message = ''; loading = false; constructor(private route: ActivatedRoute, private orders: OrdersService, private router: Router, private cart: CartService) {} ngOnInit() { this.orderId = Number(this.route.snapshot.paramMap.get('orderId')); } payNow() { this.loading = true; this.orders.pay(this.orderId).subscribe({ next: (o) => { this.status = o.status; this.message = 'Payment successful!'; this.loading = false; this.cart.clear(); this.router.navigate(['/order', this.orderId]); }, error: err => { this.message = err?.error?.detail || 'Payment failed'; this.loading = false; } }); } goOrders() { this.router.navigateByUrl('/orders'); } }
