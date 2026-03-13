import { Injectable } from "@angular/core";
import { Product } from "./products.service";
export interface CartItem {
  product: Product;
  quantity: number;
}

@Injectable({ providedIn: "root" })
export class CartService {
  private key = "ecom_cart";
  load(): CartItem[] {
    const raw = localStorage.getItem(this.key);
    return raw ? JSON.parse(raw) : [];
  }
  save(items: CartItem[]) {
    localStorage.setItem(this.key, JSON.stringify(items));
  }
  items(): CartItem[] {
    return this.load();
  }
  add(product: Product) {
    const items = this.load();
    const found = items.find((i) => i.product.id === product.id);
    if (found) found.quantity += 1;
    else items.push({ product, quantity: 1 });
    this.save(items);
  }
  remove(productId: number) {
    const items = this.load().filter((i) => i.product.id !== productId);
    this.save(items);
  }
  update(productId: number, quantity: number) {
    const items = this.load().map((i) =>
      i.product.id === productId ? { ...i, quantity } : i,
    );
    this.save(items);
  }
  clear() {
    localStorage.removeItem(this.key);
  }
  count(): number {
    return this.load().reduce((sum, i) => sum + i.quantity, 0);
  }
  totalCents(): number {
    return this.load().reduce(
      (sum, i) => sum + i.product.price_cents * i.quantity,
      0,
    );
  }
}
