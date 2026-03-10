import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { CartService } from '../../services/cart.service';
import { OrdersService } from '../../services/orders.service';
import { AuthService } from '../../services/auth.service';
import { FormsModule } from '@angular/forms';

@Component({
  standalone: true,
  selector: 'app-checkout',
  imports: [CommonModule, FormsModule],
  templateUrl: './checkout.component.html'
})
export class CheckoutComponent implements OnInit {
  address = '';
  contact_name = '';
  contact_email = '';
  contact_phone = '';
  error = '';
  loading = false;

  constructor(
    private cart: CartService,
    private orders: OrdersService,
    private router: Router,
    private auth: AuthService
  ) {
    const u = this.auth.user();
    if (u) {
      this.contact_name = this.contact_name || u.name || '';
      this.contact_email = this.contact_email || u.email || '';
      this.address = this.address || (u.default_shipping_address ?? '');
      this.contact_phone = this.contact_phone || (u.default_contact_phone ?? '');
    } else {
      this.address = this.auth.savedAddress();
      this.contact_phone = this.auth.savedPhone();
    }
  }

  ngOnInit() {
    this.auth.fetchMe().subscribe({
      next: (u) => {
        this.auth.setUser(u); // keep local storage in sync
        if (!this.contact_name)  this.contact_name  = u.name || '';
        if (!this.contact_email) this.contact_email = u.email || '';
        if (!this.address)       this.address       = u.default_shipping_address ?? '';
        if (!this.contact_phone) this.contact_phone = u.default_contact_phone ?? '';
      },
      error: () => { /* ignore */ }
    });
  }

  items() { return this.cart.items(); }
  total() { return `₹${(this.cart.totalCents()/100).toFixed(2)}`; }

  private validateRequired(): string | null {
    if (!this.items().length)       return 'Cart is empty';
    if (!this.contact_name.trim())  return 'Contact name is required';
    if (!this.contact_email.trim()) return 'Contact email is required';
    if (!this.contact_phone.trim()) return 'Contact phone is required';
    if (!this.address.trim())       return 'Shipping address is required';
    return null;
  }

  placeOrder() {
  this.error = '';
  const missing = this.validateRequired();
  if (missing) { 
    this.error = missing; 
    return; 
  }

  this.loading = true;

  const orderPayload = {
    items: this.items().map(i => ({ product_id: i.product.id, quantity: i.quantity })),
    payment_method: 'card', // Stripe payment
    shipping_address: this.address.trim(),
    contact_name: this.contact_name.trim(),
    contact_email: this.contact_email.trim(),
    contact_phone: this.contact_phone.trim()
  };

  this.orders.create(orderPayload).subscribe({
    next: (order) => {
      this.orders.pay(order.id).subscribe({
        next: (res) => {
          this.cart.clear();
          window.location.href = res.checkout_url;
        },
        error: (err) => {
          console.error("Error starting Stripe payment session:", err);
          this.error = "Failed to start payment session.";
          this.loading = false;
        }
      });
    },
    error: (err) => {
      console.error("Error creating order:", err);
      this.error = err?.error?.detail || 'Failed to create order';
      this.loading = false;
    }
  });
}
}