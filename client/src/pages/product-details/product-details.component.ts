import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { ProductsService, Product } from '../../services/products.service';
import { CartService } from '../../services/cart.service';

@Component({ standalone: true, selector: 'app-product-details', imports: [CommonModule], templateUrl: './product-details.component.html', styles: [`
  .layout{ display:grid; grid-template-columns: 1fr 1fr; gap:24px }
  @media (max-width: 900px){ .layout{ grid-template-columns: 1fr } }
  .specs{ border:1px solid var(--border); border-radius:12px; overflow:hidden }
  .row{ display:flex; }
  .cell{ flex:1; padding:10px 12px; border-bottom:1px solid var(--border) }
  .cell.key{ background:#f9fbff; color:#334155; width:40% }
`] })
export class ProductDetailsComponent implements OnInit { p?: Product; loading = true; constructor(private route: ActivatedRoute, private svc: ProductsService, private cart: CartService) {} ngOnInit() { const id = Number(this.route.snapshot.paramMap.get('id')); this.svc.get(id).subscribe(prod => { this.p = prod; this.loading = false; }); } add() { if (this.p) { this.cart.add(this.p); alert('Added to cart'); } } toCurrency(cents: number) { return `₹${(cents/100).toFixed(2)}`; } specEntries(): [string,string][] { return this.p?.specs ? Object.entries(this.p.specs) : []; } }
