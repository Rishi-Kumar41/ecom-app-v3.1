# server/seed.py
from sqlalchemy.orm import Session
from models import Product
import json

SEED_PRODUCTS = [
    {
        "name": "Samsung Galaxy S24",
        "description": "6.2\\\" Dynamic AMOLED, Snapdragon 8 Gen 3, 128GB",
        "category": "Phones",
        "price_cents": 69900,
        "image_url": "/assets/products/s24.jpg'",
        "stock": 25,
        "specs_json": json.dumps({
            "Display": "6.2\\\" AMOLED",
            "Chip": "Snapdragon 8 Gen 3",
            "Storage": "128GB"
        })
    },
    {
        "name": "Samsung Galaxy S24 Ultra",
        "description": "6.8\\\" QHD+ AMOLED, 200MP camera, 256GB",
        "category": "Phones",
        "price_cents": 129900,
        "image_url": "/assets/products/s24ultra.jpg",
        "stock": 18,
        "specs_json": json.dumps({
            "Display": "6.8\\\" QHD+",
            "Camera": "200MP",
            "Storage": "256GB"
        })
    },
    {
        "name": "Samsung Galaxy Buds2 Pro",
        "description": "ANC earbuds with Hi-Fi sound",
        "category": "Audio",
        "price_cents": 14990,
        "image_url": "/assets/products/buds2pro.jpg",
        "stock": 60,
        "specs_json": json.dumps({
            "ANC": "Yes",
            "Codecs": "SSC HiFi, AAC",
            "Battery": "18h"
        })
    },
    {
        "name": "Samsung Galaxy Watch6",
        "description": "Fitness tracking, AMOLED display, Wear OS",
        "category": "Wearables",
        "price_cents": 29990,
        "image_url": "/assets/products/watch6.jpg",
        "stock": 40,
        "specs_json": json.dumps({
            "Size": "44mm",
            "OS": "Wear OS",
            "Sensors": "HR, SpO2"
        })
    },
    {
        "name": "Samsung 27\\\" 4K Monitor",
        "description": "UHD IPS, HDR10, USB-C",
        "category": "Monitors",
        "price_cents": 34990,
        "image_url": "/assets/products/monitor27.jpg",
        "stock": 15,
        "specs_json": json.dumps({
            "Resolution": "3840x2160",
            "HDR": "HDR10",
            "USB-C": "65W PD"
        })
    },
    {
        "name": "Samsung Portable SSD T7 1TB",
        "description": "USB 3.2 Gen 2, up to 1050 MB/s",
        "category": "Storage",
        "price_cents": 8990,
        "image_url": "/assets/products/t7-1tb.jpg",
        "stock": 50,
        "specs_json": json.dumps({
            "Capacity": "1TB",
            "Speed": "Up to 1050MB/s",
            "Interface": "USB-C"
        })
    },
    {
        "name": "Samsung 990 PRO 2TB NVMe",
        "description": "PCIe 4.0 NVMe SSD",
        "category": "Storage",
        "price_cents": 16990,
        "image_url": "/assets/products/990pro-2tb.jpg",
        "stock": 30,
        "specs_json": json.dumps({
            "Capacity": "2TB",
            "Interface": "PCIe 4.0",
            "Form Factor": "M.2"
        })
    },
    {
        "name": "Samsung 65\\\" QLED TV",
        "description": "4K QLED, Quantum HDR, Smart TV",
        "category": "TVs",
        "price_cents": 104990,
        "image_url": "/assets/products/qled65.jpg",
        "stock": 8,
        "specs_json": json.dumps({
            "Size": "65\\\"",
            "Panel": "QLED",
            "Smart": "Tizen"
        })
    },
    {
        "name": "Samsung 15.6\\\" Laptop",
        "description": "Intel i7, 16GB RAM, 512GB SSD",
        "category": "Laptops",
        "price_cents": 72990,
        "image_url": "/assets/products/laptop15.jpg",
        "stock": 12,
        "specs_json": json.dumps({
            "CPU": "Intel i7",
            "RAM": "16GB",
            "Storage": "512GB SSD"
        })
    },
    {
        "name": "Samsung Wireless Charger Duo",
        "description": "Charge phone + earbuds simultaneously",
        "category": "Accessories",
        "price_cents": 3990,
        "image_url": "/assets/products/chargerduo.jpg",
        "stock": 70,
        "specs_json": json.dumps({
            "Output": "15W",
            "Devices": "Phone + Buds",
            "Cable": "USB-C"
        })
    },
]

def seed_products(db: Session):
    count = db.query(Product).count()
    if count == 0:
        for p in SEED_PRODUCTS:
            db.add(Product(**p))
        db.commit()