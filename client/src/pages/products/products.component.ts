import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ProductsService, Product, ProductQuery } from '../../services/products.service';
import { CartService } from '../../services/cart.service';
import { FormsModule } from '@angular/forms';

@Component({ standalone: true, selector: 'app-products', imports: [CommonModule, FormsModule, RouterLink], templateUrl: './products.component.html', styles: [`
  .filters{ display:grid; grid-template-columns: 1fr 160px 160px 140px 160px; gap:10px; margin-bottom:16px }
  .grid{ grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
  .title{font-weight:700}
  .muted{color:var(--muted); font-size:0.9em}
  .card .price{font-weight:700; margin-top:4px}
`] })
export class ProductsComponent implements OnInit {
  loading = true; products: Product[] = []; categories: string[] = [];
  q = ''; category = ''; min_price_cents: number | null = null; max_price_cents: number | null = null; in_stock: boolean | null = null; sort = 'price_asc';
  constructor(private svc: ProductsService, private cart: CartService) {}
  ngOnInit() { this.svc.categories().subscribe(c => this.categories = c); this.fetch(); }
  fetch() { this.loading = true; const query: ProductQuery = { q: this.q || undefined, category: this.category || undefined, min_price_cents: this.min_price_cents ?? undefined, max_price_cents: this.max_price_cents ?? undefined, in_stock: this.in_stock ?? undefined, sort: this.sort || undefined }; this.svc.list(query).subscribe(p => { this.products = p; this.loading = false; }); }
  add(p: Product) { this.cart.add(p); alert('Added to cart'); }
  toCurrency(cents: number) { return `₹${(cents/100).toFixed(2)}`; }
}
