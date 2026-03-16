import { Component } from "@angular/core";
import { RouterLink, RouterOutlet } from "@angular/router";
import { CommonModule } from "@angular/common";
import { AuthService } from "./services/auth.service";
import { CartService } from "./services/cart.service";

@Component({
  selector: "app-root",
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink],
  templateUrl: "./app.component.html",
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
