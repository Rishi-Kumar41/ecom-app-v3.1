import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink, Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({ standalone: true, selector: 'app-register', imports: [CommonModule, FormsModule, RouterLink], templateUrl: './register.component.html', styles: [`.box{max-width:420px;margin:24px auto}.card{padding:16px}`] })
export class RegisterComponent { name = ''; email = ''; password = ''; error = ''; ok = ''; constructor(private auth: AuthService, private router: Router) {} submit() { this.error = ''; this.ok = ''; this.auth.register({name: this.name, email: this.email, password: this.password}).subscribe({ next: () => { this.ok = 'Registered! Redirecting to login...'; setTimeout(()=>this.router.navigateByUrl('/login'), 800); }, error: err => this.error = err?.error?.detail || 'Registration failed' }); } }
