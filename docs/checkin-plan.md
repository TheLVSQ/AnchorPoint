# AnchorPoint Check-In System

## Overview

A self-service check-in kiosk for churches, designed to work on iPads/tablets with affordable thermal printers.

## Design Philosophy

- **Printer-agnostic**: Works with any thermal printer, not just expensive Zebra printers
- **Simple setup**: No complex print servers required
- **Secure**: Security codes match children with authorized guardians
- **Flexible**: Supports various label sizes and formats

---

## Supported Printers

### Recommended Budget Options

| Printer | Approx. Price | Connection | Notes |
|---------|---------------|------------|-------|
| Brother QL-820NWB | $150-180 | WiFi/BT/USB | **Best choice** - wireless, works great |
| Brother QL-800 | $80-100 | USB | Budget wired option |
| Generic 58/80mm thermal | $30-50 | USB/BT | Ultra budget, receipt-style |
| Epson TM-T20III | $150-180 | USB/Ethernet | Commercial receipt printer |
| Zebra ZD410/ZD420 | $300+ | USB/Ethernet | Premium option if budget allows |

### Connection Methods

1. **Direct USB** - Printer connected to a small PC/Raspberry Pi running print server
2. **WiFi/Network** - Printer with built-in WiFi (Brother QL-820NWB)
3. **Bluetooth** - For truly wireless iPad setups
4. **CUPS** - Standard Linux/Mac printing (works with any printer with drivers)

---

## Label Design

### Label Types

1. **Child Name Tag** (worn by child)
   - Child's name (large, friendly font)
   - Security code (4-character alphanumeric)
   - Room assignment
   - Allergy alert icons (if applicable)
   - Service/date

2. **Parent Claim Tag** (kept by parent)
   - Child's name
   - Matching security code
   - Service/date
   - "Present this tag at pickup"

3. **Allergy Alert Tag** (optional, for severe allergies)
   - Large "ALLERGY ALERT" header
   - Child's name
   - Specific allergies listed
   - Emergency contact

### Label Sizes Supported

- **62mm continuous** (Brother QL series) - Recommended
- **58mm thermal roll** (receipt printers)
- **80mm thermal roll** (wide receipt printers)
- **4x6 shipping labels** (for larger name tags)

---

## Architecture

### Print Service

The print service generates labels as **PNG images** - this is the universal format that works with ANY printer.

```
┌─────────────────────────────────────────────────────────────┐
│                     Check-In Flow                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  iPad Kiosk                     Print Server (optional)      │
│  ┌──────────┐                   ┌──────────────────────┐    │
│  │ Web App  │ ── HTTP/WS ────→  │ Django + Print Queue │    │
│  │ (Safari) │                   │                      │    │
│  └──────────┘                   │  ┌────────────────┐  │    │
│                                 │  │ Label Generator │  │    │
│  OR direct printing:            │  │ (Pillow/PIL)    │  │    │
│  ┌──────────┐                   │  └────────────────┘  │    │
│  │ Web App  │ ── BT/WiFi ────→  │         ↓           │    │
│  │ + WebUSB │                   │  ┌────────────────┐  │    │
│  └──────────┘                   │  │ Printer Adapter │  │    │
│                                 │  │ ESC/POS|Brother │  │    │
│                                 │  │ CUPS|ZPL        │  │    │
│                                 │  └────────────────┘  │    │
│                                 └──────────────────────┘    │
│                                           ↓                  │
│                                    ┌────────────┐           │
│                                    │  Printer   │           │
│                                    └────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

### Deployment Options

#### Option A: Centralized Print Server (Recommended)
- Raspberry Pi or small PC runs Django print service
- iPads send check-in requests over WiFi
- Server generates labels, sends to printer
- Works with USB printers (no WiFi printer required)
- **Cost: ~$50 Raspberry Pi + $50-100 printer = $100-150 total**

#### Option B: Direct WiFi Printing
- WiFi-enabled printer (Brother QL-820NWB)
- iPad sends print jobs directly
- Requires custom iOS app or uses AirPrint
- **Cost: ~$180 for printer only**

#### Option C: Bluetooth Printing
- Bluetooth thermal printer
- iPad pairs directly
- Works offline at events
- **Cost: ~$60-100 for BT printer**

---

## Database Models

### CheckInSession
```python
class CheckInSession(models.Model):
    """Represents a check-in event/service time"""
    name = models.CharField(max_length=100)  # "Sunday 9am Service"
    event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    # Rooms available for this session
    rooms = models.ManyToManyField('Room', blank=True)
```

### Room
```python
class Room(models.Model):
    """Physical room where children are checked in"""
    name = models.CharField(max_length=100)  # "Nursery", "K-2nd Grade"
    building = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)

    # Age/grade range for auto-assignment
    min_age = models.PositiveIntegerField(null=True, blank=True)
    max_age = models.PositiveIntegerField(null=True, blank=True)
    min_grade = models.CharField(max_length=10, blank=True)
    max_grade = models.CharField(max_length=10, blank=True)
```

### CheckIn
```python
class CheckIn(models.Model):
    """Individual check-in record"""
    session = models.ForeignKey(CheckInSession, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True)

    # Security code for pickup verification
    security_code = models.CharField(max_length=8)

    checked_in_at = models.DateTimeField(auto_now_add=True)
    checked_in_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    checked_out_at = models.DateTimeField(null=True, blank=True)
    checked_out_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    # Labels printed
    child_label_printed = models.BooleanField(default=False)
    parent_label_printed = models.BooleanField(default=False)

    class Meta:
        unique_together = ['session', 'person']
```

### PrinterConfiguration
```python
class PrinterConfiguration(models.Model):
    """Printer setup for a location"""
    PRINTER_TYPES = [
        ('escpos', 'ESC/POS (Generic Thermal)'),
        ('brother', 'Brother QL Series'),
        ('cups', 'CUPS/System Printer'),
        ('zpl', 'Zebra (ZPL)'),
        ('airprint', 'AirPrint'),
    ]

    name = models.CharField(max_length=100)
    printer_type = models.CharField(max_length=20, choices=PRINTER_TYPES)

    # Connection details (varies by type)
    connection_string = models.CharField(max_length=255)
    # Examples:
    # ESC/POS USB: "/dev/usb/lp0" or "usb://vendor:product"
    # ESC/POS Network: "tcp://192.168.1.100:9100"
    # Brother: "tcp://192.168.1.100:9100" or "usb://0x04f9:0x209c"
    # CUPS: "Brother_QL-820NWB"
    # ZPL: "tcp://192.168.1.100:9100"

    # Label settings
    label_width_mm = models.PositiveIntegerField(default=62)
    label_height_mm = models.PositiveIntegerField(null=True, blank=True)  # null = continuous

    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
```

### LabelTemplate
```python
class LabelTemplate(models.Model):
    """Customizable label designs"""
    LABEL_TYPES = [
        ('child', 'Child Name Tag'),
        ('parent', 'Parent Claim Tag'),
        ('allergy', 'Allergy Alert'),
        ('visitor', 'Visitor Badge'),
    ]

    name = models.CharField(max_length=100)
    label_type = models.CharField(max_length=20, choices=LABEL_TYPES)

    # Template stored as JSON with layout instructions
    template_json = models.JSONField()

    # Optional custom CSS for web preview
    preview_css = models.TextField(blank=True)

    is_default = models.BooleanField(default=False)
```

---

## Security Code System

### Generation
- 4 alphanumeric characters (easy to read)
- Excludes confusing characters: 0/O, 1/I/L, 5/S
- Valid charset: `A B C D E F G H J K M N P Q R T U V W X Y Z 2 3 4 6 7 8 9`
- ~450,000 combinations per session (more than enough)

### Family Matching
- Same security code for all family members in a session
- Parent receives ONE claim tag with the family code
- Each child gets their own name tag with the same code

### Verification
- At checkout, volunteer enters security code
- System shows all children with that code
- Volunteer confirms visual match with parent
- System logs checkout time

---

## Label Generation Service

Using **Pillow (PIL)** for universal compatibility:

```python
# checkin/services/label_generator.py

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

class LabelGenerator:
    """Generate label images that work with any printer"""

    # DPI for thermal printers (typically 203 or 300)
    DPI = 203

    def __init__(self, width_mm=62, height_mm=29):
        self.width_px = int(width_mm * self.DPI / 25.4)
        self.height_px = int(height_mm * self.DPI / 25.4)

    def generate_child_label(self, checkin, person) -> bytes:
        """Generate a child name tag as PNG"""
        img = Image.new('1', (self.width_px, self.height_px), color=1)  # 1-bit for thermal
        draw = ImageDraw.Draw(img)

        # Load fonts (bundled with app)
        font_large = ImageFont.truetype("static/fonts/OpenSans-Bold.ttf", 48)
        font_medium = ImageFont.truetype("static/fonts/OpenSans-Regular.ttf", 24)
        font_code = ImageFont.truetype("static/fonts/RobotoMono-Bold.ttf", 36)

        # Child's name (large, centered)
        name = f"{person.first_name} {person.last_name[0]}."
        draw.text((self.width_px // 2, 20), name, font=font_large, anchor="mt", fill=0)

        # Room assignment
        room = checkin.room.name if checkin.room else "Main Room"
        draw.text((self.width_px // 2, 80), room, font=font_medium, anchor="mt", fill=0)

        # Security code (prominent)
        draw.text((self.width_px // 2, 120), checkin.security_code,
                  font=font_code, anchor="mt", fill=0)

        # Allergy indicators
        if person.allergies:
            draw.rectangle([10, self.height_px - 30, 50, self.height_px - 10], fill=0)
            draw.text((30, self.height_px - 20), "!", font=font_medium, anchor="mm", fill=1)

        # Convert to bytes
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()
```

---

## Printer Adapters

### ESC/POS Adapter (Generic Thermal)
```python
# checkin/services/printers/escpos_adapter.py

from escpos.printer import Usb, Network

class ESCPOSAdapter:
    def __init__(self, connection_string):
        if connection_string.startswith('tcp://'):
            host, port = connection_string[6:].split(':')
            self.printer = Network(host, int(port))
        else:
            # USB connection
            vendor, product = parse_usb_string(connection_string)
            self.printer = Usb(vendor, product)

    def print_image(self, image_bytes: bytes):
        """Print a PNG image"""
        from PIL import Image
        from io import BytesIO

        img = Image.open(BytesIO(image_bytes))
        self.printer.image(img)
        self.printer.cut()
```

### Brother QL Adapter
```python
# checkin/services/printers/brother_adapter.py

from brother_ql.raster import BrotherQLRaster
from brother_ql.backends.helpers import send

class BrotherQLAdapter:
    def __init__(self, connection_string, model='QL-820NWB', label='62'):
        self.connection = connection_string
        self.model = model
        self.label = label

    def print_image(self, image_bytes: bytes):
        from PIL import Image
        from io import BytesIO

        img = Image.open(BytesIO(image_bytes))

        qlr = BrotherQLRaster(self.model)
        qlr.exception_on_warning = True

        from brother_ql.conversion import convert
        instructions = convert(
            qlr=qlr,
            images=[img],
            label=self.label,
            rotate='auto',
            threshold=70.0,
            dither=False,
            compress=False,
            red=False,
        )

        send(instructions=instructions, printer_identifier=self.connection,
             backend_identifier='pyusb' if 'usb://' in self.connection else 'network')
```

### CUPS Adapter (Universal)
```python
# checkin/services/printers/cups_adapter.py

import cups
import tempfile

class CUPSAdapter:
    def __init__(self, printer_name):
        self.printer_name = printer_name
        self.conn = cups.Connection()

    def print_image(self, image_bytes: bytes):
        """Print via CUPS - works with any printer with drivers"""
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(image_bytes)
            f.flush()
            self.conn.printFile(self.printer_name, f.name, "Check-in Label", {})
```

---

## Kiosk UI Flow

### Check-In Flow

```
┌─────────────────────────────────────────────────────────────┐
│  WELCOME TO [CHURCH NAME]                                    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                                                      │    │
│  │              TAP TO CHECK IN                         │    │
│  │                                                      │    │
│  │         [Large touchable button]                     │    │
│  │                                                      │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│              Already checked in? [Look up family]            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  FIND YOUR FAMILY                                            │
│                                                              │
│  Enter phone number:                                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  (555) 123-4567                                      │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌───┬───┬───┐                                              │
│  │ 1 │ 2 │ 3 │                                              │
│  ├───┼───┼───┤     [Large numeric keypad]                   │
│  │ 4 │ 5 │ 6 │                                              │
│  ├───┼───┼───┤                                              │
│  │ 7 │ 8 │ 9 │                                              │
│  ├───┼───┼───┤                                              │
│  │ ← │ 0 │ ✓ │                                              │
│  └───┴───┴───┘                                              │
│                                                              │
│  [Not found? Register as visitor]                           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  SELECT FAMILY MEMBERS TO CHECK IN                           │
│                                                              │
│  The Johnson Family                                          │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ ☑ Emma Johnson        Age 8    → Room 103           │    │
│  │ ☑ Liam Johnson        Age 5    → Room 105           │    │
│  │ ☐ Sarah Johnson       Adult    (not checking in)    │    │
│  │ ☐ Mike Johnson        Adult    (not checking in)    │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│                              [CONTINUE →]                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  ✓ CHECK-IN COMPLETE!                                        │
│                                                              │
│  Your security code is: K7M2                                 │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Emma → Room 103 (K-2nd Grade)                       │    │
│  │  Liam → Room 105 (Pre-K)                             │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  🖨️ Printing labels...                                       │
│                                                              │
│  Please keep your claim tag for pickup!                      │
│                                                              │
│                    [DONE - Return to start]                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Core Infrastructure (MVP)
- [ ] CheckIn Django app scaffolding
- [ ] Database models (CheckIn, Room, CheckInSession, PrinterConfiguration)
- [ ] Label generator service using Pillow
- [ ] ESC/POS printer adapter (covers most generic printers)
- [ ] Basic kiosk check-in flow
- [ ] Security code generation

### Phase 2: Enhanced Printing
- [ ] Brother QL adapter
- [ ] CUPS adapter (universal fallback)
- [ ] Printer configuration UI in admin
- [ ] Test print functionality
- [ ] Label template customization

### Phase 3: Kiosk Refinements
- [ ] Visitor registration flow
- [ ] Checkout/pickup verification
- [ ] Room capacity tracking
- [ ] Real-time dashboard for volunteers
- [ ] Attendance reports

### Phase 4: Advanced Features
- [ ] Pre-registration (check in from home)
- [ ] Recurring schedules
- [ ] Multiple campus support
- [ ] Custom label designs per room
- [ ] Integration with main event system

---

## Hardware Recommendations

### Minimum Budget Setup (~$150)
- Generic 58mm thermal printer (USB): $40
- Raspberry Pi 4 (2GB): $45
- SD Card + Power Supply: $25
- Used iPad (any model with Safari): $40-100 (Facebook Marketplace)

### Recommended Setup (~$300)
- Brother QL-820NWB: $180
- Used iPad: $100
- No print server needed (direct WiFi printing)

### Premium Setup (~$600)
- Brother QL-820NWB: $180
- iPad 10th Gen: $350
- iPad stand/enclosure: $50

---

## Print Server Setup (Raspberry Pi)

```bash
# On Raspberry Pi running Raspbian

# Install dependencies
sudo apt update
sudo apt install python3-pip cups libcups2-dev

# Install Python packages
pip3 install pillow python-escpos brother_ql pycups

# Enable CUPS web interface (optional)
sudo cupsctl --remote-admin

# Add printer (CUPS)
# Access http://raspberrypi.local:631 to add printer

# Run AnchorPoint print service
# (Docker or direct Python)
```

---

## API Endpoints

```
POST /api/checkin/lookup/
  - Input: { "phone": "5551234567" }
  - Returns: Family members available for check-in

POST /api/checkin/checkin/
  - Input: { "session_id": 1, "person_ids": [1, 2], "room_overrides": {} }
  - Returns: { "security_code": "K7M2", "checkins": [...] }

POST /api/checkin/print/
  - Input: { "checkin_id": 1, "label_type": "child" }
  - Triggers label print

POST /api/checkin/checkout/
  - Input: { "security_code": "K7M2" }
  - Returns: Checked-in children for verification

POST /api/checkin/checkout/confirm/
  - Input: { "checkin_ids": [1, 2] }
  - Marks children as checked out
```

---

## Cost Comparison

| Solution | Printer | Print Server | Total |
|----------|---------|--------------|-------|
| AnchorPoint + Generic | $40 | $70 (Pi) | **$110** |
| AnchorPoint + Brother WiFi | $180 | $0 | **$180** |
| Rock RMS + Zebra | $350+ | $0 | **$350+** |
| Planning Center Check-Ins | $350 (Zebra) | + $99/mo | **$350 + subscription** |

**AnchorPoint saves churches $200-400+ on hardware alone, with no monthly fees.**
