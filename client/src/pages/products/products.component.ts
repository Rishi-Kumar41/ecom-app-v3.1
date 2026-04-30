import { Component, OnInit } from "@angular/core";
import { CommonModule } from "@angular/common";
import { RouterLink } from "@angular/router";
// import {
//   ProductsService,
//   Product,
//   ProductQuery,
// } from "../../services/products.service";

import { Product } from "../../services/products.service";
import ssgProducts from "../../assets/ssg-products.json";

import { CartService } from "../../services/cart.service";
import { FormsModule } from "@angular/forms";

@Component({
  standalone: true,
  selector: "app-products",
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: "./products.component.html",
  styles: [
    `
      .filters {
        display: grid;
        grid-template-columns: 1fr 160px 160px 140px 160px;
        gap: 10px;
        margin-bottom: 16px;
      }
      .grid {
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      }
      .title {
        font-weight: 700;
      }
      .muted {
        color: var(--muted);
        font-size: 0.9em;
      }
      .card .price {
        font-weight: 700;
        margin-top: 4px;
      }
    `,
  ],
})
export class ProductsComponent implements OnInit {
  loading = true;
  products: Product[] = [];
  allProducts: Product[] = [];
  categories: string[] = [];
  q = "";
  category = "";
  min_price_cents: number | null = null;
  max_price_cents: number | null = null;
  in_stock: boolean | null = null;
  sort = "price_asc";
  
constructor(private cart: CartService) {}

  

ngOnInit() {
  // Load static snapshot for SSG
  this.allProducts = (ssgProducts as unknown as Product[]);

  // Derive categories from snapshot
  this.categories = Array.from(
    new Set(this.allProducts.map(p => p.category).filter((c): c is string => c !== undefined))
  ).sort();

  // Populate initial view using local filtering/sorting
  this.fetch();
}


  fetch() {
  this.loading = true;

  const qLower = (this.q || "").trim().toLowerCase();

  let list = [...this.allProducts];

  if (qLower) {
    list = list.filter(p =>
      (p.name || "").toLowerCase().includes(qLower) ||
      (p.description || "").toLowerCase().includes(qLower)
    );
  }

  if (this.category) {
    list = list.filter(p => p.category === this.category);
  }

  if (this.min_price_cents != null) {
    list = list.filter(p => (p.price_cents ?? 0) >= this.min_price_cents!);
  }

  if (this.max_price_cents != null) {
    list = list.filter(p => (p.price_cents ?? 0) <= this.max_price_cents!);
  }

  if (this.in_stock != null) {
    list = list.filter(p => this.in_stock ? (p.stock ?? 0) > 0 : (p.stock ?? 0) <= 0);
  }

  // Sorting
  switch (this.sort) {
    case "price_asc":
      list.sort((a, b) => (a.price_cents ?? 0) - (b.price_cents ?? 0));
      break;
    case "price_desc":
      list.sort((a, b) => (b.price_cents ?? 0) - (a.price_cents ?? 0));
      break;
    case "name_asc":
      list.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
      break;
    case "name_desc":
      list.sort((a, b) => (b.name || "").localeCompare(a.name || ""));
      break;
    default:
      break;
  }

  this.products = list;
  this.loading = false;
}

  add(p: Product) {
    this.cart.add(p);
    alert("Added to cart");
  }
  toCurrency(cents: number) {
    return `₹${(cents / 100).toFixed(2)}`;
  }

}
