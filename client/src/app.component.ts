import { Component } from "@angular/core";
import { RouterLink, RouterOutlet } from "@angular/router";
import { CommonModule } from "@angular/common";
import { AuthService } from "./services/auth.service";
import { CartService } from "./services/cart.service";

@Component({
  selector: "app-root",
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink],
  template: `
    <nav class="nav">
      <a routerLink="/">Products</a>
      <a routerLink="/agent">Agent</a>
      <a routerLink="/cart">Cart ({{ cart.count() }})</a>
      <a routerLink="/orders" *ngIf="auth.isLoggedIn()">Orders</a>
      <a routerLink="/profile" *ngIf="auth.isLoggedIn()">Profile</a>
      <span class="spacer"></span>
      <span *ngIf="auth.isLoggedIn()">Hi, {{ auth.userName() }}</span>
      <a routerLink="/login" *ngIf="!auth.isLoggedIn()">Login</a>
      <a routerLink="/register" *ngIf="!auth.isLoggedIn()">Register</a>
      <a routerLink="/logout" *ngIf="auth.isLoggedIn()">Logout</a>
    </nav>
    <main class="container"><router-outlet></router-outlet></main>
  `,
})
export class AppComponent {
  constructor(
    public auth: AuthService,
    public cart: CartService,
  ) {}
  logout(e: Event) {
    e.preventDefault();
    this.auth.logout();
  }
}
