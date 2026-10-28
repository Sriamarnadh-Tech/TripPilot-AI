import { useState } from "react";

const API = "http://127.0.0.1:8000";

const initialForm = {
  destination: "Jaipur",
  startDate: "2026-10-28",
  endDate: "2026-10-30",
  budget: "15000",
  travelers: "2",
  interests: ["History", "Food"],
  travelStyle: "Balanced",
};

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join(", ")
      : detail || "Request failed";

    throw new Error(message);
  }

  return data;
}

function formatINR(value) {
  return Number(value || 0).toLocaleString("en-IN", {
    maximumFractionDigits: 0,
  });
}

export default function App() {
  const [form, setForm] = useState(initialForm);

  const [discoverDestination, setDiscoverDestination] =
    useState("Jaipur");
  const [discoverCategory, setDiscoverCategory] =
    useState("both");
  const [places, setPlaces] = useState(null);
  const [discoverBusy, setDiscoverBusy] = useState(false);

  const [trip, setTrip] = useState(null);
  const [planResult, setPlanResult] = useState(null);
  const [history, setHistory] = useState(null);

  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [disruptionType, setDisruptionType] =
    useState("closure");
  const [evidenceSource, setEvidenceSource] =
    useState("user_report");
  const [confidence, setConfidence] = useState("0.9");
  const [corroborated, setCorroborated] = useState(false);
  const [conflicting, setConflicting] = useState(false);
  const [expired, setExpired] = useState(false);
  const [newBudget, setNewBudget] = useState("10000");

  function updateForm(field, value) {
    setForm((previous) => ({
      ...previous,
      [field]: value,
    }));
  }

  function notify(text) {
    setMessage(text);
    setError("");
  }

  function notifyError(text) {
    setError(text);
    setMessage("");
  }

  async function discoverPlaces(event) {
    event?.preventDefault();

    if (!discoverDestination.trim()) {
      notifyError("Enter a destination first.");
      return;
    }

    setDiscoverBusy(true);
    setPlaces(null);
    setError("");
    setMessage("");

    try {
      const query = new URLSearchParams({
        destination: discoverDestination.trim(),
        category: discoverCategory,
        radius_m: "7000",
        limit: "30",
      });

      const result = await apiRequest(
        `/api/discover/places?${query.toString()}`
      );

      setPlaces(result);
      notify(`Found ${result.count} mapped place listings.`);
    } catch (err) {
      notifyError(`Place discovery failed: ${err.message}`);
    } finally {
      setDiscoverBusy(false);
    }
  }

  async function createTrip(event) {
    event.preventDefault();

    setBusy(true);
    setPlanResult(null);
    setError("");
    setMessage("");

    try {
      const payload = {
        ...form,
        budget: Number(form.budget),
        travelers: Number(form.travelers),
      };

      const result = await apiRequest("/api/trips/plan", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      setTrip(result);
      setNewBudget(String(result.trip.budget));
      setPlanResult(null);
      setHistory(null);

      notify(`Trip created. Trip ID: ${result.trip_id}`);
    } catch (err) {
      notifyError(`Trip creation failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function refreshHistory() {
    if (!trip) return;

    try {
      const result = await apiRequest(
        `/api/trips/${trip.trip_id}/history`
      );
      setHistory(result);
      notify("Trip history refreshed.");
    } catch (err) {
      notifyError(`Could not load history: ${err.message}`);
    }
  }

  async function assessAndReplan() {
    if (!trip) return;

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const now = Date.now();

      const evidence = {
        disruption_type: disruptionType,
        affected_day: 1,
        affected_activity_index: 0,
        source: evidenceSource || "user_report",
        observed_at: new Date(now - 60 * 60 * 1000).toISOString(),
        valid_until: new Date(
          now + (expired ? -60 * 60 * 1000 : 6 * 60 * 60 * 1000)
        ).toISOString(),
        confidence: Number(confidence),
        claim: `User-simulated ${disruptionType} disruption`,
        corroborating_sources: corroborated
          ? ["additional_user_report"]
          : [],
        conflicting_claims: conflicting
          ? ["Another report disputes this claim"]
          : [],
      };

      const result = await apiRequest("/api/trips/replan", {
        method: "POST",
        body: JSON.stringify({
          trip_id: trip.trip_id,
          evidence,
        }),
      });

      setPlanResult(result);

      setTrip((previous) => ({
        ...previous,
        itinerary: result.current_itinerary,
        validation: result.validation,
      }));

      notify(`Decision: ${result.decision}. ${result.reason}`);

      const updatedHistory = await apiRequest(
        `/api/trips/${trip.trip_id}/history`
      );
      setHistory(updatedHistory);
    } catch (err) {
      notifyError(`Replanning failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function updateBudget() {
    if (!trip) return;

    const amount = Number(newBudget);

    if (!Number.isFinite(amount) || amount <= 0) {
      notifyError("Enter a valid positive budget.");
      return;
    }

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const result = await apiRequest("/api/trips/budget", {
        method: "POST",
        body: JSON.stringify({
          trip_id: trip.trip_id,
          new_budget: amount,
        }),
      });

      setTrip((previous) => ({
        ...previous,
        itinerary: result.itinerary,
        validation: result.validation,
        trip: {
          ...previous.trip,
          budget: amount,
        },
      }));

      setPlanResult(null);
      notify("Budget update completed.");

      const updatedHistory = await apiRequest(
        `/api/trips/${trip.trip_id}/history`
      );
      setHistory(updatedHistory);
    } catch (err) {
      notifyError(`Budget update failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  const itinerary =
    planResult?.current_itinerary || trip?.itinerary;

  const validation =
    planResult?.validation || trip?.validation;

  return (
    <div>
      <nav className="navbar navbar-dark topbar">
        <div className="container">
          <a className="navbar-brand fw-bold" href="#">
            ✈ AdaptiveTrip
          </a>
          <span className="text-light">
            Evidence-aware travel planning
          </span>
        </div>
      </nav>

      <main className="container py-4">
        <header className="hero mb-4">
          <small>TRAVEL RESEARCH PROTOTYPE</small>
          <h1>Discover places. Plan smarter. Adapt when plans change.</h1>
          <p>
            Find mapped attractions and restaurants, create a trip,
            and experiment with evidence-aware replanning.
          </p>
        </header>

        {message && (
          <div className="alert alert-success" role="status">
            {message}
          </div>
        )}

        {error && (
          <div className="alert alert-danger" role="alert">
            {error}
          </div>
        )}

        {/* LIVE PLACE DISCOVERY */}
        <section className="cardbox mb-4">
          <div className="eyebrow">EXPLORE</div>
          <h2 className="h4 mt-2">
            Discover real attractions and restaurants
          </h2>

          <p className="text-secondary">
            Search mapped listings near a destination. Data is
            supplied by OpenStreetMap; ratings and exact prices
            are not fabricated.
          </p>

          <form onSubmit={discoverPlaces}>
            <div className="row g-3 align-items-end">
              <div className="col-md-6">
                <label className="form-label">Destination</label>
                <input
                  className="form-control"
                  value={discoverDestination}
                  onChange={(event) =>
                    setDiscoverDestination(event.target.value)
                  }
                  placeholder="e.g. Jaipur, India"
                  required
                />
              </div>

              <div className="col-md-3">
                <label className="form-label">Category</label>
                <select
                  className="form-select"
                  value={discoverCategory}
                  onChange={(event) =>
                    setDiscoverCategory(event.target.value)
                  }
                >
                  <option value="both">Places & restaurants</option>
                  <option value="attractions">Attractions</option>
                  <option value="restaurants">Restaurants & cafes</option>
                </select>
              </div>

              <div className="col-md-3">
                <button
                  className="btn btn-primary w-100"
                  type="submit"
                  disabled={discoverBusy}
                >
                  {discoverBusy ? "Searching..." : "Discover places"}
                </button>
              </div>
            </div>
          </form>

          {places && (
            <div className="mt-4">
              <div className="d-flex justify-content-between flex-wrap gap-2 mb-3">
                <div>
                  <h3 className="h5 mb-1">
                    {places.count} result(s)
                  </h3>
                  <div className="small text-secondary">
                    {places.resolved_location}
                  </div>
                </div>

                <span className="badge text-bg-light align-self-start">
                  Source: OpenStreetMap
                </span>
              </div>

              {places.count === 0 ? (
                <div className="alert alert-warning">
                  No named places were found. Try a larger destination
                  or a different category.
                </div>
              ) : (
                <div className="row g-3">
                  {places.places.map((place) => (
                    <div className="col-md-6" key={place.id}>
                      <article className="placecard h-100">
                        <div className="d-flex justify-content-between gap-2">
                          <h3 className="h6 fw-bold">
                            {place.name}
                          </h3>

                          <span className="badge text-bg-secondary align-self-start">
                            {place.category}
                          </span>
                        </div>

                        <p className="small text-secondary mb-2">
                          {place.place_type}
                          {place.cuisine
                            ? ` · ${place.cuisine.replaceAll(";", ", ")}`
                            : ""}
                        </p>

                        {place.address && (
                          <p className="small mb-2">
                            📍 {place.address}
                          </p>
                        )}

                        {place.opening_hours && (
                          <p className="small mb-2">
                            🕒 {place.opening_hours}
                          </p>
                        )}

                        {place.price_level && (
                          <p className="small mb-2">
                            Price information: {place.price_level}
                          </p>
                        )}

                        <p className="small text-secondary">
                          {place.rating === null
                            ? "Rating unavailable from this source"
                            : `Rating: ${place.rating}`}
                        </p>

                        <div className="d-flex flex-wrap gap-3 small">
                          <a
                            href={place.map_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open map ↗
                          </a>

                          <a
                            href={place.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            View source ↗
                          </a>

                          {place.website && (
                            <a
                              href={place.website}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Website ↗
                            </a>
                          )}
                        </div>
                      </article>
                    </div>
                  ))}
                </div>
              )}

              <div className="small text-secondary mt-3">
                {places.data_notes.join(" ")}
              </div>
            </div>
          )}
        </section>

        {/* TRIP CREATION AND ITINERARY */}
        <div className="row g-4">
          <section className="col-lg-5">
            <div className="cardbox">
              <h2 className="h4">Plan your trip</h2>

              <form onSubmit={createTrip}>
                <label className="form-label">Destination</label>
                <input
                  className="form-control mb-3"
                  value={form.destination}
                  onChange={(event) =>
                    updateForm("destination", event.target.value)
                  }
                  required
                />

                <div className="row">
                  <div className="col-6">
                    <label className="form-label">Start date</label>
                    <input
                      type="date"
                      className="form-control mb-3"
                      value={form.startDate}
                      onChange={(event) =>
                        updateForm("startDate", event.target.value)
                      }
                      required
                    />
                  </div>

                  <div className="col-6">
                    <label className="form-label">End date</label>
                    <input
                      type="date"
                      className="form-control mb-3"
                      value={form.endDate}
                      onChange={(event) =>
                        updateForm("endDate", event.target.value)
                      }
                      required
                    />
                  </div>
                </div>

                <div className="row">
                  <div className="col-6">
                    <label className="form-label">Budget (₹)</label>
                    <input
                      type="number"
                      min="1"
                      className="form-control mb-3"
                      value={form.budget}
                      onChange={(event) =>
                        updateForm("budget", event.target.value)
                      }
                      required
                    />
                  </div>

                  <div className="col-6">
                    <label className="form-label">Travelers</label>
                    <input
                      type="number"
                      min="1"
                      max="10"
                      className="form-control mb-3"
                      value={form.travelers}
                      onChange={(event) =>
                        updateForm("travelers", event.target.value)
                      }
                      required
                    />
                  </div>
                </div>

                <label className="form-label">Travel style</label>
                <select
                  className="form-select mb-3"
                  value={form.travelStyle}
                  onChange={(event) =>
                    updateForm("travelStyle", event.target.value)
                  }
                >
                  <option>Budget-friendly</option>
                  <option>Balanced</option>
                  <option>Comfort</option>
                </select>

                <label className="form-label">Interests</label>

                <div className="d-flex flex-wrap gap-2 mb-4">
                  {[
                    "History",
                    "Food",
                    "Nature",
                    "Adventure",
                    "Shopping",
                    "Relaxation",
                  ].map((interest) => (
                    <label className="badgebox" key={interest}>
                      <input
                        type="checkbox"
                        checked={form.interests.includes(interest)}
                        onChange={(event) => {
                          const selected = event.target.checked
                            ? [...form.interests, interest]
                            : form.interests.filter(
                                (item) => item !== interest
                              );

                          updateForm("interests", selected);
                        }}
                      />{" "}
                      {interest}
                    </label>
                  ))}
                </div>

                <button
                  className="btn btn-primary w-100"
                  type="submit"
                  disabled={busy}
                >
                  {busy ? "Working..." : "Generate itinerary"}
                </button>
              </form>
            </div>
          </section>

          <section className="col-lg-7">
            {!trip ? (
              <div className="cardbox empty">
                <h2 className="h4">Your itinerary appears here</h2>
                <p>
                  Create a trip to see its itinerary and activate
                  the replanning controls.
                </p>
              </div>
            ) : (
              <div className="cardbox">
                <div className="d-flex justify-content-between gap-3">
                  <div>
                    <div className="eyebrow">CURRENT TRIP</div>
                    <h2 className="h3 mt-2">
                      {trip.trip.destination}
                    </h2>
                    <p>
                      {trip.trip.trip_days} day(s) ·{" "}
                      {trip.trip.travelers} traveler(s)
                    </p>
                  </div>

                  <span className="badge text-bg-primary align-self-start">
                    Revision {planResult?.revision ?? 0}
                  </span>
                </div>

                <div className="row g-2 mb-3">
                  {[
                    ["Budget", validation?.budget ?? trip.trip.budget],
                    ["Estimated cost", validation?.estimated_total_cost ?? 0],
                    ["Remaining", validation?.remaining_budget ?? 0],
                  ].map(([label, amount]) => (
                    <div className="col-4" key={label}>
                      <div className="stat">
                        <small>{label}</small>
                        <strong>₹{formatINR(amount)}</strong>
                      </div>
                    </div>
                  ))}
                </div>

                {validation && (
                  <div
                    className={`alert ${
                      validation.is_valid
                        ? "alert-success"
                        : "alert-danger"
                    }`}
                  >
                    <strong>
                      {validation.is_valid
                        ? "Constraint checks passed"
                        : "Validation issues found"}
                    </strong>

                    {validation.errors?.map((item, index) => (
                      <div key={`error-${index}`}>{item}</div>
                    ))}

                    {validation.warnings?.map((item, index) => (
                      <div className="small" key={`warning-${index}`}>
                        {item}
                      </div>
                    ))}
                  </div>
                )}

                {itinerary?.map((day) => (
                  <div className="daybox" key={day.day}>
                    <div className="d-flex justify-content-between gap-2">
                      <h3 className="h6 fw-bold">
                        DAY {day.day} · {day.date}
                      </h3>
                      <strong>₹{formatINR(day.estimated_daily_cost)}</strong>
                    </div>

                    {day.activities.map((activity, index) => (
                      <div
                        className="activity"
                        key={`${day.day}-${index}`}
                      >
                        <strong className="time">
                          {activity.time}
                        </strong>

                        <div className="flex-grow-1">
                          <strong>{activity.title}</strong>
                          <small>
                            {activity.duration_minutes} min · illustrative
                            activity
                          </small>
                        </div>

                        <span>
                          ₹{formatINR(activity.estimated_cost)}
                        </span>
                      </div>
                    ))}
                  </div>
                ))}

                <div className="alert alert-warning mt-3 mb-0">
                  Live place discovery is available above, but these
                  itinerary activities and costs are still illustrative.
                  Connecting discovered places to itinerary generation
                  is our next development step.
                </div>
              </div>
            )}
          </section>
        </div>

        {/* EVIDENCE AND REPLANNING */}
        {trip && (
          <>
            <section className="cardbox mt-4">
              <div className="eyebrow">DISRUPTION LAB</div>
              <h2 className="h4 mt-2">
                Assess evidence and decide
              </h2>

              <p className="text-secondary">
                This is currently a simulated evidence workflow.
                It does not automatically monitor live disruptions.
              </p>

              <div className="row g-3">
                <div className="col-md-4">
                  <label className="form-label">Disruption</label>
                  <select
                    className="form-select"
                    value={disruptionType}
                    onChange={(event) =>
                      setDisruptionType(event.target.value)
                    }
                  >
                    <option value="weather">Weather</option>
                    <option value="closure">Attraction closure</option>
                    <option value="transport">Transport</option>
                  </select>
                </div>

                <div className="col-md-4">
                  <label className="form-label">Evidence source</label>
                  <input
                    className="form-control"
                    value={evidenceSource}
                    onChange={(event) =>
                      setEvidenceSource(event.target.value)
                    }
                  />
                </div>

                <div className="col-md-4">
                  <label className="form-label">Confidence (0–1)</label>
                  <input
                    type="number"
                    className="form-control"
                    min="0"
                    max="1"
                    step="0.05"
                    value={confidence}
                    onChange={(event) =>
                      setConfidence(event.target.value)
                    }
                  />
                </div>

                <div className="col-md-4">
                  <label className="form-label">Corroboration</label>
                  <select
                    className="form-select"
                    value={String(corroborated)}
                    onChange={(event) =>
                      setCorroborated(event.target.value === "true")
                    }
                  >
                    <option value="false">Absent</option>
                    <option value="true">Present</option>
                  </select>
                </div>

                <div className="col-md-4">
                  <label className="form-label">Conflicting report</label>
                  <select
                    className="form-select"
                    value={String(conflicting)}
                    onChange={(event) =>
                      setConflicting(event.target.value === "true")
                    }
                  >
                    <option value="false">None</option>
                    <option value="true">Present</option>
                  </select>
                </div>

                <div className="col-md-4">
                  <label className="form-label">Evidence validity</label>
                  <select
                    className="form-select"
                    value={String(expired)}
                    onChange={(event) =>
                      setExpired(event.target.value === "true")
                    }
                  >
                    <option value="false">Current</option>
                    <option value="true">Expired</option>
                  </select>
                </div>
              </div>

              <button
                className="btn btn-primary mt-3 me-2"
                disabled={busy}
                onClick={assessAndReplan}
              >
                {busy ? "Processing..." : "Assess evidence & replan"}
              </button>

              <button
                className="btn btn-outline-secondary mt-3"
                disabled={busy}
                onClick={refreshHistory}
              >
                Refresh history
              </button>
            </section>

            <section className="cardbox mt-4">
              <h2 className="h5">Update travel budget</h2>

              <div className="d-flex flex-wrap gap-2">
                <input
                  className="form-control budgetinput"
                  type="number"
                  min="1"
                  value={newBudget}
                  onChange={(event) =>
                    setNewBudget(event.target.value)
                  }
                />

                <button
                  className="btn btn-outline-primary"
                  disabled={busy}
                  onClick={updateBudget}
                >
                  Replan budget
                </button>
              </div>
            </section>
          </>
        )}

        {planResult && (
          <section className="cardbox mt-4">
            <div className="eyebrow">DECISION REPORT</div>
            <h2 className="h4 mt-2 text-capitalize">
              {planResult.decision.replaceAll("_", " ")}
            </h2>

            <p>{planResult.reason}</p>

            <p>
              Evidence status:{" "}
              <strong>
                {planResult.evidence_assessment.status}
              </strong>
              {" · "}
              Revision: <strong>{planResult.revision}</strong>
              {" · "}
              Changes: <strong>{planResult.changes.length}</strong>
            </p>

            {planResult.changes.length === 0 ? (
              <p>No activity changed for this evidence report.</p>
            ) : (
              planResult.changes.map((change, index) => (
                <div className="changebox" key={index}>
                  <p>Before: {change.old_activity}</p>
                  <p>
                    After: <strong>{change.new_activity}</strong>
                  </p>
                  <small>{change.reason}</small>
                </div>
              ))
            )}
          </section>
        )}

        {history && (
          <section className="cardbox mt-4">
            <h2 className="h4">Evidence and revision history</h2>

            <p>
              {history.evidence.length} evidence record(s) ·{" "}
              {history.revisions.length} revision(s)
            </p>

            {history.evidence.map((item) => (
              <div className="changebox" key={item.id}>
                <strong>
                  #{item.id} · {item.evidence.disruption_type} ·{" "}
                  {item.assessment.status}
                </strong>

                <div>
                  {item.evidence.source} · confidence{" "}
                  {item.evidence.confidence}
                </div>

                <small>
                  {item.assessment.decision}:{" "}
                  {item.assessment.reason}
                </small>
              </div>
            ))}
          </section>
        )}

        <footer className="text-center text-secondary small py-5">
          TripPilot research prototype · No bookings or payments
        </footer>
      </main>
    </div>
  );
}