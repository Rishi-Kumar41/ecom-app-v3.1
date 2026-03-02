import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AuthService, User } from '../../services/auth.service';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';

@Component({
    standalone: true,
    selector: 'app-profile',
    imports: [CommonModule, RouterLink, FormsModule],
    templateUrl: './profile.component.html'
})
export class ProfileComponent implements OnInit {
    user?: User;

    // Local, editable fields for saving default address & phone
    address = '';
    phone = '';

    // UI feedback
    saving = false;
    ok = '';
    err = '';


    constructor(private auth: AuthService,) {

    }

    ngOnInit() {
        this.auth.fetchMe().subscribe(u => { 
            this.user = u;
            this.auth.setUser(u);
            this.address = u.default_shipping_address ?? '';
            this.phone = u.default_contact_phone ?? '';
        });
    }


    saveAddress() {
        this.ok = '';
        this.err = '';
        this.saving = true;

        // basic guard in UI; server also validates body shape
        if (!this.address.trim()) {
        this.err = 'Please enter a shipping address.';
        this.saving = false;
        return;
        }

        this.auth.saveAddress({
        default_shipping_address: this.address.trim(),
        default_contact_phone: this.phone?.trim() || undefined
        }).subscribe({
        next: (u) => {
            this.user = u;
            this.auth.setUser(u);  // keep local storage in sync
            this.ok = 'Saved!';
            this.saving = false;
        },
        error: (e) => {
            this.err = e?.error?.detail || 'Failed to save address';
            this.saving = false;
        }
        });
    }

}
