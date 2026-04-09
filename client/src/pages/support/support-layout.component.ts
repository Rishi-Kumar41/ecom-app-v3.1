// client/src/pages/support/support-layout.component.ts
import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AdminService, AdminSearchItem } from '../../services/admin.service';
import { AssistFloatingComponent } from '../../components/assist-floating/assist-floating.component';

@Component({
  standalone: true,
  selector: 'app-support-layout',
  imports: [CommonModule, FormsModule, AssistFloatingComponent],
  templateUrl: './support-layout.component.html',
  styleUrls: ['./support-layout.component.css'],
})
export class SupportLayoutComponent implements OnInit {

  q = '';
  k = 10;
  // NEW: source filter + retrieval mode (hooked to /admin/search?type=&hybrid=)
  type: 'product' | 'order' | 'user' | 'policy' | 'any' = 'any';
  hybrid = true; // set true if you want RRF fusion for admin search too
  loading = false;
  error = '';
  results: AdminSearchItem[] = []


  constructor(private router: Router, private admin: AdminService) {}

  ngOnInit() {
    // this.search(false);
  }

  
search(requireQuery: boolean = true) {
    this.error = '';
    if (requireQuery && !this.q.trim()) {
      this.results = [];
      return;
    }

    this.loading = true;
    this.admin.search(this.q, this.k, this.type, this.hybrid).subscribe({
      next: (res) => {
        this.results = res?.items ?? [];
        this.loading = false;
      },
      error: (e) => {
        this.error = e?.error?.detail || 'Search failed';
        this.loading = false;
      },
    });
  }

  goToAdd() {
    this.router.navigate(['/support/products/new']);
  }
}