"""tests/test_route_advisor.py — RouteAdvisor tests"""
from __future__ import annotations
import math, time, sqlite3
import pytest
from agents.route_advisor import RouteAdvisor, HAZARD_WEIGHTS, HAZARD_DECAY_H

_LAT, _LON = 13.0827, 80.2707

@pytest.fixture
def ra(tmp_path): return RouteAdvisor(db_path=str(tmp_path / "h.db"))

class TestHazardRecording:
    def test_record_retrieve(self, ra):
        ra.record_hazard("n1","pothole",0.9,_LAT,_LON)
        hits = ra.get_hazards_near(_LAT,_LON,radius_m=200)
        assert len(hits)==1 and hits[0]["hazard_class"]=="pothole"
    def test_outside_radius(self, ra):
        ra.record_hazard("n2","road_work",0.8,_LAT+0.01,_LON)
        assert ra.get_hazards_near(_LAT,_LON,radius_m=100) == []
    def test_multiple(self, ra):
        for h in ("pothole","road_work","debris"):
            ra.record_hazard("n",h,0.8,_LAT,_LON)
        assert len(ra.get_hazards_near(_LAT,_LON,radius_m=200)) == 3
    def test_distance_field(self, ra):
        ra.record_hazard("n","pothole",1.0,_LAT,_LON)
        assert "distance_m" in ra.get_hazards_near(_LAT,_LON)[0]
    def test_old_filtered(self, ra):
        old_ts = time.time() - 3*3600
        with ra._connect() as c:
            c.execute("INSERT INTO hazard_reports (node_id,hazard_class,confidence,lat,lon,reported_at) VALUES (?,?,?,?,?,?)",
                      ("old","pothole",0.9,_LAT,_LON,old_ts)); c.commit()
        hits = ra.get_hazards_near(_LAT,_LON,max_age_h=1.0)
        assert all(h["reported_at"]>old_ts for h in hits)

class TestRouteScoring:
    def test_empty(self, ra):    assert ra.score_route([]) == 0.0
    def test_no_hazards(self, ra): assert ra.score_route([(_LAT,_LON)]) == 0.0
    def test_with_hazard(self, ra):
        ra.record_hazard("x","pothole",0.9,_LAT,_LON)
        assert ra.score_route([(_LAT,_LON)]) > 0
    def test_high_conf_scores_higher(self, ra):
        la, lb = (_LAT, _LON), (_LAT+0.009, _LON)
        ra.record_hazard("ha","pothole",1.0,la[0],la[1])
        ra.record_hazard("lb","pothole",0.1,lb[0],lb[1])
        assert ra.score_route([la]) > ra.score_route([lb])
    def test_dedup_adjacent_waypoints(self, ra):
        ra.record_hazard("dup","pothole",1.0,_LAT,_LON)
        s1 = ra.score_route([(_LAT,_LON)])
        s2 = ra.score_route([(_LAT,_LON),(_LAT+0.00001,_LON+0.00001)])
        assert s1 == s2
    def test_old_hazard_lower_score(self, ra):
        old_ts = time.time() - HAZARD_DECAY_H*3600*2
        new_ts = time.time()
        with ra._connect() as c:
            c.execute("INSERT INTO hazard_reports (node_id,hazard_class,confidence,lat,lon,reported_at) VALUES (?,?,?,?,?,?)",
                      ("o","pothole",1.0,_LAT,_LON,old_ts)); 
            c.execute("INSERT INTO hazard_reports (node_id,hazard_class,confidence,lat,lon,reported_at) VALUES (?,?,?,?,?,?)",
                      ("n","pothole",1.0,_LAT+0.002,_LON,new_ts)); c.commit()
        assert ra.score_route([(_LAT+0.002,_LON)]) > ra.score_route([(_LAT,_LON)])

class TestRecommend:
    def test_no_routes(self, ra):  assert "error" in ra.recommend([])
    def test_single(self, ra):
        r = ra.recommend([[(13.08,80.27),(13.09,80.28)]])
        assert r["recommended_index"] == 0
    def test_safest_wins(self, ra):
        for _ in range(3): ra.record_hazard("r0","pothole",0.9,_LAT,_LON)
        result = ra.recommend([[ (_LAT,_LON) ], [ (13.10,80.30) ]], labels=["Haz","Clear"])
        assert result["recommended_index"] == 1 and result["recommended_label"]=="Clear"
    def test_structure(self, ra):
        r = ra.recommend([[(13.08,80.27)],[(13.10,80.30)]], labels=["A","B"])
        assert "recommended_index" in r and "scores" in r and len(r["routes"])==2
    def test_default_labels(self, ra):
        r = ra.recommend([[(13.0,80.0)],[(13.1,80.1)]])
        assert r["routes"][0]["label"] == "Route 1"

class TestLiveFeed:
    def test_empty(self, ra):     assert isinstance(ra.get_live_hazard_feed(), list)
    def test_recent_shows(self, ra):
        ra.record_hazard("lv","road_work",0.8,_LAT,_LON)
        feed = ra.get_live_hazard_feed(max_age_h=1.0)
        assert any(h["hazard_class"]=="road_work" for h in feed)
    def test_limit(self, ra):
        for i in range(10): ra.record_hazard(f"l{i}","pothole",0.5,_LAT+i*0.0001,_LON)
        assert len(ra.get_live_hazard_feed(max_age_h=1.0,limit=3)) <= 3
    def test_age_min_field(self, ra):
        ra.record_hazard("am","pothole",1.0,_LAT,_LON)
        feed = ra.get_live_hazard_feed(max_age_h=1.0)
        assert "age_min" in feed[0] and feed[0]["age_min"] >= 0
