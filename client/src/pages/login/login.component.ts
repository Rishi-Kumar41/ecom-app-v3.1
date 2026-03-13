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
  constructor(
    private auth: AuthService,
    private router: Router,
    private route: ActivatedRoute,
  ) {}
  submit() {
    this.error = "";
    this.loading = true;
    this.auth.login(this.email, this.password).subscribe({
      next: (res) => {
        this.auth.saveToken(res.access_token);
        this.auth.fetchMe().subscribe((u) => {
          this.auth.setUser(u);
          this.router.navigateByUrl("/");
        });
      },
      error: (err) => {
        this.error = err?.error?.detail || "Login failed";
        this.loading = false;
      },
    });
    const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl') || '/';
    this.router.navigateByUrl(returnUrl);
  }
}
