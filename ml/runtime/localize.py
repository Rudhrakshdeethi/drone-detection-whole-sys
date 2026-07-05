"""Single-node 3D localization — turn one camera + LiDAR + pan/tilt into a GPS fix.

Why this exists: most cheap drone detectors only tell you *that* a drone is
present. This node tells you *where* — an absolute latitude/longitude/altitude —
from a **single** sensor head, by fusing three cheap measurements the rig already
produces every frame:

    * a camera **bounding-box centre** (where the drone sits in the frame),
    * the **pan/tilt** angles the servo gimbal is currently pointed at, and
    * a **LiDAR range** (TF-Luna, metres) along the camera's optical axis.

The pipeline is pure geometry (numpy only, no hardware):

    bbox centre + pan/tilt  ->  absolute azimuth / elevation      (bbox_to_bearing)
    azimuth / elevation / range  ->  local East/North/Up offset   (polar_to_enu)
    ENU offset + sensor GPS  ->  target latitude / longitude / alt (enu_to_latlon)

    fix = localize(cx, cy, range_m, pan_deg, tilt_deg, lat, lon)
    # {"azimuth_deg","elevation_deg","east_m","north_m","up_m",
    #  "lat","lon","alt","range_m"}

Conventions used throughout:
    * Azimuth is compass-style: 0 deg = North, +90 deg = East (clockwise from N).
    * Elevation is 0 deg at the horizon, +90 deg straight up.
    * Pan follows the same azimuth convention; tilt follows elevation.
    * ENU = local tangent plane: +East, +North, +Up in metres.
    * FOV defaults are the Raspberry Pi Camera v2 (H 62.2 deg, V 48.8 deg).
"""
from __future__ import annotations
import numpy as np

# Mean Earth radius (WGS-84 mean), metres — good to <0.3% anywhere on Earth.
_EARTH_R = 6_371_000.0


def bbox_to_bearing(cx: float, cy: float, pan_deg: float, tilt_deg: float,
                    hfov_deg: float = 62.2, vfov_deg: float = 48.8
                    ) -> tuple[float, float]:
    """Absolute (azimuth, elevation) of a bbox centre, in degrees.

    The camera points at ``(pan_deg, tilt_deg)``; the object's bounding-box
    centre sits at normalized image coordinates ``(cx, cy)`` where (0, 0) is the
    top-left corner and (1, 1) is bottom-right, so (0.5, 0.5) is dead centre.

    We treat the lens as an ideal rectilinear pinhole: horizontal image angle is
    linear in ``cx`` across the field of view. A centre at cx=0.5 is on-axis
    (offset 0); cx=1.0 is +hfov/2 to the right, cx=0.0 is -hfov/2 to the left::

        d_az = (cx - 0.5) * hfov          # right of frame  -> larger azimuth
        d_el = (0.5 - cy) * vfov          # top   of frame  -> larger elevation

    Note the vertical sign flip: image *y* grows downward, elevation grows
    upward, so we use ``(0.5 - cy)``. The offsets add to the gimbal pointing to
    give an absolute bearing; azimuth is wrapped into ``[0, 360)``.
    """
    d_az = (float(cx) - 0.5) * float(hfov_deg)
    d_el = (0.5 - float(cy)) * float(vfov_deg)
    azimuth = (float(pan_deg) + d_az) % 360.0
    elevation = float(tilt_deg) + d_el
    return azimuth, elevation


def polar_to_enu(azimuth_deg: float, elevation_deg: float, range_m: float
                 ) -> tuple[float, float, float]:
    """Local East/North/Up offset (metres) of a target at a given bearing+range.

    Standard spherical-to-Cartesian on the local tangent plane, using the
    compass/elevation convention (az measured clockwise from North, el from the
    horizon). With slant ``range_m`` r::

        horizontal = r * cos(el)          # ground-plane component
        up    = r * sin(el)
        east  = horizontal * sin(az)      # az=0 -> due North, az=90 -> due East
        north = horizontal * cos(az)

    Returns ``(east, north, up)`` in metres relative to the sensor.
    """
    az = np.radians(float(azimuth_deg))
    el = np.radians(float(elevation_deg))
    horizontal = float(range_m) * np.cos(el)
    up = float(range_m) * np.sin(el)
    east = horizontal * np.sin(az)
    north = horizontal * np.cos(az)
    return float(east), float(north), float(up)


def enu_to_latlon(sensor_lat: float, sensor_lon: float, sensor_alt: float,
                  east: float, north: float, up: float
                  ) -> tuple[float, float, float]:
    """Add a local ENU offset (metres) to a GPS origin -> (lat, lon, alt).

    Equirectangular (flat-Earth) approximation: over the small offsets a single
    sensor can range to (a TF-Luna reaches ~8 m, a good LiDAR a few hundred),
    the tangent plane is effectively flat, so we convert metres to degrees with
    a constant scale::

        dlat = north / R                              # metres North per radian lat
        dlon = east  / (R * cos(sensor_lat))          # longitude lines converge

    The ``cos(sensor_lat)`` term accounts for meridians drawing together toward
    the poles. Error stays well under a metre for offsets up to a few km, which
    is far beyond any single-node LiDAR range — perfectly adequate here.
    Altitude is a straight metres add.
    """
    lat0 = np.radians(float(sensor_lat))
    dlat = float(north) / _EARTH_R
    dlon = float(east) / (_EARTH_R * np.cos(lat0))
    lat = float(sensor_lat) + np.degrees(dlat)
    lon = float(sensor_lon) + np.degrees(dlon)
    alt = float(sensor_alt) + float(up)
    return lat, lon, alt


def localize(cx: float, cy: float, range_m: float, pan_deg: float,
             tilt_deg: float, sensor_lat: float, sensor_lon: float,
             sensor_alt: float = 0.0, **fov) -> dict:
    """Full single-node fix: pixel + LiDAR range + gimbal pose -> GPS target.

    Args:
        cx, cy:       normalized bbox centre in [0, 1] (top-left origin).
        range_m:      slant range to the target in metres (from the TF-Luna).
        pan_deg:      gimbal azimuth (deg, clockwise from North).
        tilt_deg:     gimbal elevation (deg above the horizon).
        sensor_lat/lon/alt: the sensor head's own GPS position.
        **fov:        optional ``hfov_deg`` / ``vfov_deg`` overrides for the lens.

    Returns a dict with the intermediate bearing, the ENU offset, and the final
    target ``lat``/``lon``/``alt`` (plus the ``range_m`` passed through).
    """
    azimuth, elevation = bbox_to_bearing(cx, cy, pan_deg, tilt_deg, **fov)
    east, north, up = polar_to_enu(azimuth, elevation, range_m)
    lat, lon, alt = enu_to_latlon(sensor_lat, sensor_lon, sensor_alt,
                                  east, north, up)
    return {
        "azimuth_deg": round(azimuth, 3),
        "elevation_deg": round(elevation, 3),
        "east_m": round(east, 3),
        "north_m": round(north, 3),
        "up_m": round(up, 3),
        "lat": round(lat, 8),
        "lon": round(lon, 8),
        "alt": round(alt, 3),
        "range_m": float(range_m),
    }


def main(argv=None):
    import json
    # Worked example: sensor on a rooftop in Bangalore, gimbal panned to due
    # North-East and tilted 20 deg up. The drone shows up slightly right-of- and
    # above-centre in the frame, 30 m away per the TF-Luna.
    sensor_lat, sensor_lon, sensor_alt = 12.97160, 77.59460, 30.0
    fix = localize(
        cx=0.62, cy=0.40,          # a bit right and above frame centre
        range_m=30.0,              # TF-Luna slant range, metres
        pan_deg=45.0, tilt_deg=20.0,
        sensor_lat=sensor_lat, sensor_lon=sensor_lon, sensor_alt=sensor_alt,
    )
    print("single-node localization — worked example")
    print(f"  sensor : lat={sensor_lat} lon={sensor_lon} alt={sensor_alt} m")
    print(f"  bearing: az={fix['azimuth_deg']} deg  el={fix['elevation_deg']} deg")
    print(f"  ENU    : E={fix['east_m']} N={fix['north_m']} U={fix['up_m']} m")
    print(f"  TARGET : lat={fix['lat']} lon={fix['lon']} alt={fix['alt']} m")
    print(json.dumps(fix, indent=2))

    # Sanity self-test: a straight-up shot must land essentially overhead.
    up_fix = localize(0.5, 0.5, 25.0, 0.0, 90.0, sensor_lat, sensor_lon, 0.0)
    assert abs(up_fix["east_m"]) < 1e-6 and abs(up_fix["north_m"]) < 1e-6
    assert abs(up_fix["up_m"] - 25.0) < 1e-6
    assert abs(up_fix["lat"] - sensor_lat) < 1e-7
    print("\nself-test OK (straight-up shot stays overhead, +25 m altitude)")


if __name__ == "__main__":
    main()
