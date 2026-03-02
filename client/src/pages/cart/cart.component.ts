import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { CartService, CartItem } from '../../services/cart.service';
import { RouterLink, Router } from '@angular/router';

@Component({ standalone: true, selector: 'app-cart', imports: [CommonModule, RouterLink], templateUrl: './cart.component.html' })
export class CartComponent { constructor(public cart: CartService, private router: Router) {} items(): CartItem[] { return this.cart.items(); } total() { return `₹${(this.cart.totalCents()/100).toFixed(2)}`; } inc(id: number) { const it = this.items().find(i => i.product.id === id); if (it) this.cart.update(id, it.quantity + 1); } dec(id: number) { const it = this.items().find(i => i.product.id === id); if (it) this.cart.update(id, Math.max(1, it.quantity - 1)); } remove(id: number) { this.cart.remove(id); } checkout() { this.router.navigateByUrl('/checkout'); } }
