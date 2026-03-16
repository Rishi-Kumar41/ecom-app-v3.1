import { Component } from "@angular/core";
import { CommonModule } from "@angular/common";
import { FormsModule } from "@angular/forms";
import { Router, RouterLink, ActivatedRoute } from "@angular/router";
import { AuthService } from "../../services/auth.service";

@Component({
  standalone: true,
  selector: "app-login",
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: "./login.component.html",
  styles: [
    `
      .box {
        max-width: 420px;
        margin: 24px auto;
      }
      .box .card {
        padding: 16px;
      }
    `,
  ],
})
export class LoginComponent {
  email = "";
  password = "";
  error = "";
  loading = false;
  mode: "user" | "admin" = "user";
  constructor(
    private auth: AuthService,
    private router: Router,
    private route: ActivatedRoute,
  ) {}
  submit() {
    this.error = "";
    this.loading = true;

    // Login → save token → fetch /me
    this.auth.login(this.email, this.password).subscribe({
      next: (res) => {
        this.auth.saveToken(res.access_token);

        this.auth.fetchMe().subscribe({
          next: (u) => {
            this.auth.setUser(u);

            // If user selected "Login as Admin" but doesn't have admin role → block login
            if (this.mode === "admin" && u.role !== "admin") {
              try {
                localStorage.removeItem("ecom_token");
                localStorage.removeItem("ecom_user");
                localStorage.removeItem("ecom_cart");
              } catch {}
              this.loading = false;
              this.error = "This account does not have admin access.";
              return;
            }

            // Route by actual role
            const returnUrl =
              this.route.snapshot.queryParamMap.get("returnUrl") || "/";
            if (u.role === "admin") {
              this.router.navigateByUrl("/support");
            } else {
              this.router.navigateByUrl(returnUrl);
            }
          },
          error: () => {
            try {
              localStorage.removeItem("ecom_token");
              localStorage.removeItem("ecom_user");
            } catch {}
            this.loading = false;
            this.error = "Unable to load account. Please try again.";
          },
        });
      },
      error: (err) => {
        this.error = err?.error?.detail || "Login failed";
        this.loading = false;
      },
    });
  }
  setMode(m: "user" | "admin") {
    this.mode = m;
    this.error = "";
  }
}
