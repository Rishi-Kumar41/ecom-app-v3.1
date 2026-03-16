// client/src/pages/support/add-product/add-product.component.ts
import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AdminService, AdminCreateProductPayload } from '../../../services/admin.service';

@Component({
  standalone: true,
  selector: 'app-add-product',
  imports: [CommonModule, FormsModule],
  templateUrl: './add-product.component.html',
  styleUrls: ['./add-product.component.css'],
})
export class AddProductComponent {
  // Form model
  name = '';
  category = '';
  price_cents: number | null = null;
  stock: number | null = null;
  description = '';
  image_url = '';

  // UI feedback
  saving = false;
  ok = '';
  err = '';

  constructor(private router: Router, private admin: AdminService) {}

  get canSave(): boolean {
    return Boolean(
      this.name.trim() &&
      this.description.trim() &&
      typeof this.price_cents === 'number' && this.price_cents >= 0 &&
      typeof this.stock === 'number' && this.stock >= 0
    );
  }

  save() {
    this.ok = '';
    this.err = '';
    if (!this.canSave) return;

    const payload: AdminCreateProductPayload = {
      name: this.name.trim(),
      category: this.category.trim() || null,
      price_cents: this.price_cents ?? 0,
      stock: this.stock ?? 0,
      description: this.description.trim() || null,
      image_url: this.image_url.trim() || null,
    };

    this.saving = true;
    this.admin.createProduct(payload).subscribe({
      next: (res) => {
        // For now backend is a stub or simple create—show confirmation
        this.ok = 'Product submitted successfully.';
        this.saving = false;
        // Optional: clear form
        // this.resetForm();
        // Optional: navigate back to Support after a moment
        // setTimeout(() => this.router.navigate(['/support']), 600);
        // eslint-disable-next-line no-console
        console.log('[admin/products] response:', res);
      },
      error: (e) => {
        this.err = e?.error?.detail || 'Failed to create product';
        this.saving = false;
      },
    });
  }

  back() {
    this.router.navigate(['/support']);
  }

  resetForm() {
    this.name = '';
    this.category = '';
    this.price_cents = null;
    this.stock = null;
    this.description = '';
    this.image_url = '';
  }
}