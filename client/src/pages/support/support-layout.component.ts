// client/src/pages/support/support-layout.component.ts
import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

@Component({
  standalone: true,
  selector: 'app-support-layout',
  imports: [CommonModule, FormsModule],
  templateUrl: './support-layout.component.html',
  styleUrls: ['./support-layout.component.css'],
})
export class SupportLayoutComponent {
  q = '';

  constructor(private router: Router) {}

  goToSearch() {
    const qp = this.q?.trim() ? { q: this.q.trim() } : {};
    this.router.navigate(['/support/search'], { queryParams: qp });
  }

  goToAdd() {
    this.router.navigate(['/support/products/new']);
  }
}