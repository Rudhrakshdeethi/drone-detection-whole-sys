"""Multi-node position fix — the honest, feasible alternative to true TDOA.

Why NOT TDOA: time-difference-of-arrival multilateration recovers a position
from the *nanosecond* differences in when an RF wavefront reaches each node. At
the speed of light 1 metre of accuracy needs ~3.3 ns of timing agreement between
nodes — sub-microsecond clock discipline (GPSDO / white-rabbit / shared
reference) this commodity hardware simply does not have. So we deliberately do
NOT pretend to do TDOA.

What we do instead — two geometry methods every node already has the inputs for:

    triangulate_bearings  cross-bearing fix. Each node reports the compass
                          bearing to the target (from its gimbal / DoA antenna).
                          Two or more bearing *lines* are intersected in
                          least-squares -> the target point. (a.k.a. "resection"
                          / cross-fixing, the classic direction-finding method.)

    triangulate_rssi      RSSI multilateration (trilateration). Each node
                          estimates a *range* to the target from signal strength
                          (a path-loss model). Three or more range *circles* are
                          intersected in least-squares -> the target point.

Both are pure numpy and both work on a **local equirectangular tangent plane**:
lat/lon are converted to local East/North metres about a reference (the first
node), the intersection is solved in metres, then converted back to lat/lon.
This reuses ``localize.enu_to_latlon``'s flat-Earth approximation exactly (see
that module) — valid because inter-node baselines here are at most a few km.

ACCURACY DEPENDS ON GEOMETRY: like every multilateration method, the fix is
only as good as the node geometry. Bearings that cross near 90 deg (or range
circles with good angular spread / a wide baseline) give a tight, well-
conditioned fix; nearly-parallel bearings or collinear nodes give a long,
ill-conditioned error ellipse. Spread the nodes out.

    fix = triangulate_bearings([{"lat":..,"lon":..,"bearing_deg":..}, ...])
    fix = triangulate_rssi([{"lat":..,"lon":..,"range_m":..}, ...])
    # {"lat","lon","n_nodes","residual_m"}

Conventions (shared with localize.py):
    * Bearing is compass-style: 0 deg = North, +90 deg = East (clockwise from N).
    * ENU local plane: +East, +North metres about the reference node.
"""
from __future__ import annotations
import numpy as np

# Mean Earth radius (WGS-84 mean), metres — identical constant to localize.py.
_EARTH_R = 6_371_000.0


def _latlon_to_en(lat: float, lon: float, ref_lat: float, ref_lon: float
                  ) -> tuple[float, float]:
    """Local East/North metres of (lat, lon) about a reference (ref_lat, ref_lon).

    Inverse of ``localize.enu_to_latlon``'s equirectangular step: longitude
    lines converge by ``cos(ref_lat)``, latitude scales straight by the Earth
    radius. Flat-Earth-valid for the few-km baselines between detector nodes.
    """
    lat0 = np.radians(float(ref_lat))
    north = np.radians(float(lat) - float(ref_lat)) * _EARTH_R
    east = np.radians(float(lon) - float(ref_lon)) * _EARTH_R * np.cos(lat0)
    return float(east), float(north)


def _en_to_latlon(east: float, north: float, ref_lat: float, ref_lon: float
                  ) -> tuple[float, float]:
    """Local East/North metres -> lat/lon (the exact ``localize.enu_to_latlon``
    equirectangular map, minus altitude). Reference is the origin (0, 0)."""
    lat0 = np.radians(float(ref_lat))
    lat = float(ref_lat) + np.degrees(float(north) / _EARTH_R)
    lon = float(ref_lon) + np.degrees(float(east) / (_EARTH_R * np.cos(lat0)))
    return float(lat), float(lon)


def triangulate_bearings(nodes: list[dict]) -> dict:
    """Least-squares cross-bearing intersection of >=2 bearing lines.

    Each node is ``{"lat","lon","bearing_deg"}``: its GPS position plus the
    compass bearing (0 = North, clockwise) from that node toward the target.
    This is direction-finding *resection*, NOT time-difference TDOA — no clock
    sync is needed, only that the bearings are honest.

    Method: on the local EN plane a node at ``p`` with unit bearing direction
    ``d`` defines a ray ``p + t d``. A point ``x``'s perpendicular distance to
    that line is ``n . (x - p)`` where ``n`` is ``d`` rotated 90 deg. Stacking
    ``n . x = n . p`` for every node gives an over-determined linear system
    solved by ``np.linalg.lstsq``; the residual is the RMS perpendicular miss
    distance in metres (a direct geometry/quality indicator).

    Returns ``{"lat","lon","n_nodes","residual_m"}``. Raises ``ValueError`` for
    fewer than two nodes.
    """
    if len(nodes) < 2:
        raise ValueError("triangulate_bearings needs >= 2 nodes")
    ref_lat, ref_lon = float(nodes[0]["lat"]), float(nodes[0]["lon"])

    A, b = [], []
    for nd in nodes:
        px, py = _latlon_to_en(nd["lat"], nd["lon"], ref_lat, ref_lon)
        az = np.radians(float(nd["bearing_deg"]))
        # Bearing direction on EN plane: East = sin(az), North = cos(az).
        dx, dy = np.sin(az), np.cos(az)
        # Normal to the bearing line (d rotated +90 deg).
        nx, ny = dy, -dx
        A.append([nx, ny])
        b.append(nx * px + ny * py)

    A = np.asarray(A, dtype=float)
    b = np.asarray(b, dtype=float)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    east, north = float(sol[0]), float(sol[1])
    residual = float(np.sqrt(np.mean((A @ sol - b) ** 2)))

    lat, lon = _en_to_latlon(east, north, ref_lat, ref_lon)
    return {
        "lat": round(lat, 8),
        "lon": round(lon, 8),
        "n_nodes": len(nodes),
        "residual_m": round(residual, 3),
    }


def triangulate_rssi(nodes: list[dict], iters: int = 20) -> dict:
    """Least-squares trilateration from >=3 RSSI-derived range circles.

    Each node is ``{"lat","lon","range_m"}``: its GPS position plus an estimated
    straight-line distance to the target (typically from an RSSI path-loss
    model). This is range multilateration, NOT time-difference TDOA — the ranges
    come from signal strength, not synchronized arrival times.

    Method: on the local EN plane each node constrains
    ``|x - p_i| = r_i``. That is non-linear, so we solve it by Gauss-Newton:
    linearize the residual ``|x - p_i| - r_i`` about the current estimate and
    take least-squares steps (seeded at the range-weighted node centroid). A
    handful of iterations converge for any reasonable geometry. The returned
    residual is the RMS range mismatch in metres.

    Returns ``{"lat","lon","n_nodes","residual_m"}``. Raises ``ValueError`` for
    fewer than three nodes.
    """
    if len(nodes) < 3:
        raise ValueError("triangulate_rssi needs >= 3 nodes")
    ref_lat, ref_lon = float(nodes[0]["lat"]), float(nodes[0]["lon"])

    P = np.array([_latlon_to_en(nd["lat"], nd["lon"], ref_lat, ref_lon)
                  for nd in nodes], dtype=float)
    r = np.array([float(nd["range_m"]) for nd in nodes], dtype=float)

    x = P.mean(axis=0)                              # seed at the node centroid
    for _ in range(int(iters)):
        diff = x - P                               # (N, 2) vectors node->estimate
        dist = np.linalg.norm(diff, axis=1)
        dist = np.where(dist < 1e-9, 1e-9, dist)   # guard divide-by-zero
        residuals = dist - r                       # (N,) how far off each circle
        J = diff / dist[:, None]                   # (N, 2) Jacobian rows = unit dirs
        step, *_ = np.linalg.lstsq(J, -residuals, rcond=None)
        x = x + step
        if np.linalg.norm(step) < 1e-6:
            break

    dist = np.linalg.norm(x - P, axis=1)
    residual = float(np.sqrt(np.mean((dist - r) ** 2)))
    lat, lon = _en_to_latlon(float(x[0]), float(x[1]), ref_lat, ref_lon)
    return {
        "lat": round(lat, 8),
        "lon": round(lon, 8),
        "n_nodes": len(nodes),
        "residual_m": round(residual, 3),
    }


def main(argv=None):
    import json
    # Ground truth: a target near a set of three detector nodes in Bangalore.
    # Nodes are spread out (good geometry) around a ~1 km area.
    tgt_lat, tgt_lon = 12.97600, 77.59900
    node_pos = [
        (12.97160, 77.59460),      # SW
        (12.98050, 77.59500),      # NW
        (12.97500, 77.60300),      # E
    ]

    # --- synthesize each node's true bearing + true range to the target -------
    bearing_nodes, rssi_nodes = [], []
    for lat, lon in node_pos:
        e, n = _latlon_to_en(tgt_lat, tgt_lon, lat, lon)   # target in node's EN
        bearing = (np.degrees(np.arctan2(e, n))) % 360.0   # compass az node->tgt
        rng = float(np.hypot(e, n))
        bearing_nodes.append({"lat": lat, "lon": lon,
                              "bearing_deg": round(bearing, 4)})
        rssi_nodes.append({"lat": lat, "lon": lon, "range_m": round(rng, 3)})

    def _err_m(fix):
        e, n = _latlon_to_en(fix["lat"], fix["lon"], tgt_lat, tgt_lon)
        return float(np.hypot(e, n))

    print("multi-node triangulation self-test (cross-bearing + RSSI, NOT TDOA)")
    print(f"  target : lat={tgt_lat} lon={tgt_lon}\n")

    bf = triangulate_bearings(bearing_nodes)
    print("cross-bearing fix:")
    print(json.dumps(bf, indent=2))
    print(f"  error vs truth: {_err_m(bf):.3f} m\n")

    rf = triangulate_rssi(rssi_nodes)
    print("RSSI trilateration fix:")
    print(json.dumps(rf, indent=2))
    print(f"  error vs truth: {_err_m(rf):.3f} m\n")

    assert _err_m(bf) < 5.0, "bearing fix should recover target within a few m"
    assert _err_m(rf) < 5.0, "RSSI fix should recover target within a few m"
    print("self-test OK (both methods recover the target within a few metres)")


if __name__ == "__main__":
    main()
