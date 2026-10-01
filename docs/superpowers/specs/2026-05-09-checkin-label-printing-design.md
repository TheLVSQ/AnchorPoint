# Check-In Label Printing — Design Spec

## Overview

Add silent server-side label printing to the kiosk check-in flow. When a family completes check-in, labels print directly to a Brother QL (DK-2205 62mm continuous tape) or ESC/POS thermal printer over the network or USB — no browser print dialog.

The browser `window.print()` fallback remains for environments without a configured printer.

## Architecture

Three layers:

```
kiosk_confirmation view
  → PrintService.print_checkins(checkins, session)
      → LabelGenerator: PIL images for each child label + pickup tag
      → Adapter (BrotherQLAdapter or ESCPOSAdapter): sends to printer
```

All errors are caught and logged — a printer failure never blocks check-in completion.

## Label Generator (`checkin/services/label_generator.py`)

Generates PIL images at **696px wide** (62mm at 300 DPI — Brother QL's required resolution for 62mm tape).

### Child label (~210px tall / ~17mm)
Per checked-in child:
- Name: bold, large (36pt)
- Room name: medium (18pt), below name
- Security code: bold, right-aligned (36pt)
- Icons: ✚ (red, 20pt) if `person.allergies`, shield SVG-style box if `person.custody_flag`
- Bottom strip: session name + date (10pt, muted)

### Pickup tag (~190px tall / ~16mm)
One tag per check-in group:
- Security code: very large, centred (72pt, bold)
- Children's first names joined with · (14pt, below code)
- Session + date (10pt, bottom)

### Font
`DejaVu Sans` — installed via `fonts-dejavu-core` apt package in the Dockerfile. Path: `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` and `DejaVuSans-Bold.ttf`.

### Public API
```python
class LabelGenerator:
    @staticmethod
    def build_label_set(checkins, session) -> list[PIL.Image.Image]:
        """Returns list of PIL images: one child label per check-in + one pickup tag."""
```

## Printer Adapters (`checkin/services/printers.py`)

Both implement:
```python
def print_images(self, images: list[PIL.Image.Image]) -> bool: ...
def is_available(self) -> bool: ...
def test_print(self) -> bool: ...
```

### `BrotherQLAdapter`
- Uses `brother_ql` library
- `printer_identifier`: `tcp://192.168.x.x` (network) or `usb:///dev/usb/lp0` (USB)
- `ql_model`: `QL-800`, `QL-810W`, etc.
- Converts PIL images to Brother QL raster, sends with `brother_ql.backends.helpers.send()`
- `cut=True` between labels, `rotate='0'`, `dither=False`

### `ESCPOSAdapter`
- Uses `python-escpos` library
- `connection_string`: `host:port` (e.g. `192.168.1.101:9100`)
- Uses `escpos.printer.Network` for network, `escpos.printer.Usb` for USB
- Prints each image with `p.image(img)`, cuts between labels with `p.cut()`

### Adapter selection in `get_printer_adapter()`
```python
ADAPTERS = {
    "brother_ql": BrotherQLAdapter,
    "escpos": ESCPOSAdapter,
}
```
`printer_type` on `PrinterConfiguration` selects the adapter.

## Print Service Update (`checkin/services/print_service.py`)

Add `print_checkins()` method to `PrintService`:

```python
def print_checkins(self, checkins, session) -> bool:
    """
    Generate and print labels for a completed check-in.
    Returns True on success, False on any error.
    Never raises — printer failures must not interrupt check-in flow.
    """
    if not self.printer_config or not self.adapter:
        return False
    try:
        images = LabelGenerator.build_label_set(checkins, session)
        return self.adapter.print_images(images)
    except Exception:
        logger.exception("Label print failed for check-in group")
        return False
```

## Model Change

Add `ql_model` to `PrinterConfiguration`:

```python
QL_MODEL_CHOICES = [
    ("QL-700", "QL-700"),
    ("QL-800", "QL-800"),
    ("QL-810W", "QL-810W"),
    ("QL-820NWB", "QL-820NWB"),
    ("QL-1100", "QL-1100"),
    ("QL-1110NWB", "QL-1110NWB"),
]

ql_model = models.CharField(
    max_length=20,
    choices=QL_MODEL_CHOICES,
    default="QL-800",
    blank=True,
)
```

One new migration required.

`printer_type` should have explicit choices added:
```python
PRINTER_TYPE_CHOICES = [
    ("brother_ql", "Brother QL"),
    ("escpos", "ESC/POS Thermal"),
]
```

## View Update (`checkin/views.py`)

`kiosk_confirmation` calls print service after fetching check-ins:

```python
from .services.print_service import PrintService

def kiosk_confirmation(request):
    ...
    checkins = CheckIn.objects.filter(pk__in=checkin_ids).select_related("person", "room")
    session = _get_active_session(request)

    printer_ok = PrintService().print_checkins(checkins, session)

    return render(request, "checkin/kiosk/confirmation.html", {
        "checkins": checkins,
        "security_code": security_code,
        "session": session,
        "org": org,
        "printer_ok": printer_ok,
    })
```

## Template Update (`confirmation.html`)

Replace unconditional `window.print()` with conditional fallback:

```javascript
window.addEventListener('load', function() {
    {% if not printer_ok %}
    window.print();
    {% endif %}
});
```

Subtitle changes from "Labels are printing now" to:
```html
{% if printer_ok %}
    <div class="kiosk-subtitle">Labels are printing now</div>
{% else %}
    <div class="kiosk-subtitle">Print your labels below</div>
{% endif %}
```

## Docker Changes

### `docker/requirements.txt`
```
brother_ql==0.11.0
python-escpos==3.1
```

### `docker/Dockerfile`
Add to `apt-get install`:
```
fonts-dejavu-core \
libusb-1.0-0 \
```
`libusb-1.0-0` is required by `brother_ql` for USB backend.

### `docker/docker-compose.yml`
Add commented-out USB device passthrough to `web` service:

```yaml
    # Uncomment to enable USB printer access:
    # devices:
    #   - /dev/usb/lp0:/dev/usb/lp0
```

## Printer Admin Setup (existing UI)

No new views needed. The existing printer admin pages (`/checkin/printers/`) already handle CRUD for `PrinterConfiguration`. The new `ql_model` field and `printer_type` choices will appear automatically via `PrinterConfigForm(fields="__all__")`.

The existing test print endpoint at `POST /checkin/printers/<id>/test/` calls `PrintService.test_printer()` which calls `adapter.test_print()` — this still works with the new adapters.

## Error Handling

- If `printer_config` is `None` (no active printer configured): `print_checkins()` returns `False`, fallback to `window.print()`
- If adapter raises any exception: caught, logged, returns `False`, fallback kicks in
- If `brother_ql`/`python-escpos` not importable (not installed): `ImportError` caught in adapter `__init__`, logs warning, `is_available()` returns `False`

## Files Changed

| File | Change |
|------|--------|
| `docker/requirements.txt` | Add `brother_ql`, `python-escpos` |
| `docker/Dockerfile` | Add `fonts-dejavu-core`, `libusb-1.0-0` |
| `docker/docker-compose.yml` | Add commented USB `devices:` |
| `anchorpoint/checkin/services/printers.py` | New: `BrotherQLAdapter`, `ESCPOSAdapter` |
| `anchorpoint/checkin/services/label_generator.py` | New: PIL label generation |
| `anchorpoint/checkin/services/print_service.py` | Add `print_checkins()` |
| `anchorpoint/checkin/services/__init__.py` | Export `LabelGenerator` |
| `anchorpoint/checkin/models.py` | Add `ql_model`, `printer_type` choices |
| `anchorpoint/checkin/migrations/` | New migration |
| `anchorpoint/checkin/views.py` | Call `print_checkins()` in `kiosk_confirmation` |
| `anchorpoint/checkin/templates/checkin/kiosk/confirmation.html` | Conditional `window.print()` |

No new URL patterns. No new templates.

## Testing

- `LabelGenerator.build_label_set()` returns correct number of images (one per child + one pickup tag)
- `kiosk_confirmation` with no active printer → `printer_ok=False`, template shows print fallback
- `kiosk_confirmation` with mocked print success → `printer_ok=True`, `window.print()` not called
- `BrotherQLAdapter.print_images()` called with correct images (mock `brother_ql`)
- `ESCPOSAdapter.print_images()` called with correct images (mock `escpos`)
- Print failure (exception in adapter) → `print_checkins()` returns `False`, does not raise
