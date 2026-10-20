
import { useState } from "react";

const interests = [
  "Nature",
  "Adventure",
  "History",
  "Food",
  "Shopping",
  "Relaxation",
];

function App() {
  const [form, setForm] = useState({
    destination: "",
    startDate: "",
    endDate: "",
    budget: "",
    travelers: "2",
    travelStyle: "Balanced",
  });

  const [selectedInterests, setSelectedInterests] = useState([]);
  const [message, setMessage] = useState("");
  const [itinerary, setItinerary] = useState(null);

  const updateField = (event) => {
    setForm({ ...form, [event.target.name]: event.target.value });
  };

  const toggleInterest = (interest) => {
    setSelectedInterests((previous) =>
      previous.includes(interest)
        ? previous.filter((item) => item !== interest)
        : [...previous, interest]
    );
  };

  
const handleSubmit = async (event) => {
  event.preventDefault();
  setMessage("");
  setItinerary(null);

  if (
    !form.destination.trim() ||
    !form.startDate ||
    !form.endDate ||
    !form.budget
  ) {
    setMessage("Please fill in all required fields.");
    return;
  }

  if (form.endDate < form.startDate) {
    setMessage("End date must be on or after the start date.");
    return;
  }

  if (Number(form.budget) <= 0) {
    setMessage("Please enter a budget greater than zero.");
    return;
  }

  const tripRequest = {
    ...form,
    budget: Number(form.budget),
    travelers: Number(form.travelers),
    interests: selectedInterests,
  };

  try {
    setMessage("Sending trip details to TripPilot AI...");

    const response = await fetch(
      "http://127.0.0.1:8000/api/trips/plan",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(tripRequest),
      }
    );

    const data = await response.json();

    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map((error) => error.msg).join(", ")
        : data.detail || "Request failed";

      throw new Error(detail);
    }

    console.log("TripPilot API response:", data);

setItinerary(data);

setMessage(
  `Success! ${data.trip.destination}: ${data.trip.trip_days} day(s).`
);
  } catch (error) {
    setMessage(`Unable to create trip request: ${error.message}`);
  }
};


  return (
    <div className="app-shell">
      <nav className="navbar navbar-expand-lg bg-white border-bottom py-3">
        <div className="container">
          <a className="navbar-brand fw-bold fs-4" href="#">
            <span className="brand-icon">✈</span> TripPilot
            <span className="brand-ai"> AI</span>
          </a>
          <span className="badge rounded-pill text-bg-light border px-3 py-2">
            Smart Travel Planner
          </span>
        </div>
      </nav>

      <main>
        <section className="hero-section">
          <div className="container py-5">
            <div className="row align-items-center g-5">
              <div className="col-lg-7">
                <span className="hero-tag">
                  YOUR JOURNEY, INTELLIGENTLY PLANNED
                </span>
                <h1 className="display-3 fw-bold mt-3 hero-title">
                  Less planning.
                  <br />
                  <span>More exploring.</span>
                </h1>
                <p className="lead text-secondary mt-4 hero-description">
                  Your personal AI travel planner that builds itineraries
                  around your budget, interests and schedule — and adapts
                  when plans change.
                </p>

                <div className="d-flex flex-wrap gap-3 mt-4">
                  <div className="feature-chip">✦ Personalized trips</div>
                  <div className="feature-chip">↻ Dynamic replanning</div>
                  <div className="feature-chip">₹ Budget aware</div>
                </div>
              </div>

              <div className="col-lg-5">
                <div className="journey-card">
                  <div className="journey-illustration">🌍</div>
                  <div className="small text-uppercase text-secondary fw-semibold">
                    Your next adventure
                  </div>
                  <h3 className="fw-bold mt-2">One trip. Smarter decisions.</h3>
                  <p className="text-secondary mb-4">
                    Create a plan that works for you, with room to adapt.
                  </p>
                  <div className="journey-step">
                    <span>01</span>
                    <div>
                      <strong>Tell us your preferences</strong>
                      <p>Destination, budget and interests</p>
                    </div>
                  </div>
                  <div className="journey-step">
                    <span>02</span>
                    <div>
                      <strong>Build your itinerary</strong>
                      <p>Activities, timing and estimated costs</p>
                    </div>
                  </div>
                  <div className="journey-step">
                    <span>03</span>
                    <div>
                      <strong>Adapt when plans change</strong>
                      <p>Find alternatives when needed</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="container planner-section py-5" id="planner">
          <div className="text-center mb-5">
            <span className="section-label">START YOUR JOURNEY</span>
            <h2 className="fw-bold mt-2">Plan your next trip</h2>
            <p className="text-secondary">
              Tell us a little about your ideal getaway.
            </p>
          </div>

          <form className="planner-card" onSubmit={handleSubmit}>
            <div className="row g-4">
              <div className="col-12">
                <label className="form-label fw-semibold">
                  Where do you want to go? *
                </label>
                <input
                  className="form-control form-control-lg"
                  name="destination"
                  value={form.destination}
                  onChange={updateField}
                  placeholder="e.g. Jaipur, Manali, Goa"
                  required
                />
              </div>

              <div className="col-md-6">
                <label className="form-label fw-semibold">Start date *</label>
                <input
                  className="form-control"
                  type="date"
                  name="startDate"
                  value={form.startDate}
                  onChange={updateField}
                  min={new Date().toISOString().slice(0, 10)}
                  required
                />
              </div>

              <div className="col-md-6">
                <label className="form-label fw-semibold">End date *</label>
                <input
                  className="form-control"
                  type="date"
                  name="endDate"
                  value={form.endDate}
                  onChange={updateField}
                  min={form.startDate || new Date().toISOString().slice(0, 10)}
                  required
                />
              </div>

              <div className="col-md-6">
                <label className="form-label fw-semibold">
                  Total trip budget (₹) *
                </label>
                <input
                  className="form-control"
                  type="number"
                  name="budget"
                  min="1"
                  value={form.budget}
                  onChange={updateField}
                  placeholder="e.g. 15000"
                  required
                />
                <div className="form-text">
                  Enter your total budget for the trip.
                </div>
              </div>

              <div className="col-md-6">
                <label className="form-label fw-semibold">
                  Number of travelers
                </label>
                <select
                  className="form-select"
                  name="travelers"
                  value={form.travelers}
                  onChange={updateField}
                >
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((number) => (
                    <option key={number} value={number}>
                      {number} {number === 1 ? "traveler" : "travelers"}
                    </option>
                  ))}
                </select>
              </div>

              <div className="col-12">
                <label className="form-label fw-semibold">
                  What do you enjoy?
                </label>
                <div className="d-flex flex-wrap gap-2">
                  {interests.map((interest) => (
                    <button
                      key={interest}
                      type="button"
                      className={`interest-button ${
                        selectedInterests.includes(interest) ? "selected" : ""
                      }`}
                      onClick={() => toggleInterest(interest)}
                      aria-pressed={selectedInterests.includes(interest)}
                    >
                      {selectedInterests.includes(interest) ? "✓ " : "+ "}
                      {interest}
                    </button>
                  ))}
                </div>
              </div>

              <div className="col-12">
                <label className="form-label fw-semibold">Travel style</label>
                <div className="row g-3">
                  {[
                    {
                      name: "Budget-friendly",
                      description: "Keep costs low",
                    },
                    {
                      name: "Balanced",
                      description: "Comfort and value",
                    },
                    {
                      name: "Comfort",
                      description: "Prioritize convenience",
                    },
                  ].map((style) => (
                    <div className="col-md-4" key={style.name}>
                      <button
                        type="button"
                        className={`style-option w-100 ${
                          form.travelStyle === style.name ? "active" : ""
                        }`}
                        onClick={() =>
                          setForm({ ...form, travelStyle: style.name })
                        }
                      >
                        <strong>{style.name}</strong>
                        <small>{style.description}</small>
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              <div className="col-12">
                <button className="btn btn-primary btn-lg w-100 plan-button" type="submit">
                  Create my trip plan <span className="ms-2">→</span>
                </button>
                {message && (
                  <div className="alert alert-info mt-3 mb-0" role="status">
                    {message}
                  </div>
                )}
              </div>
            </div>
          </form>
          
          {itinerary && (
            <div className="mt-5">
              <div className="text-center mb-4">
                <span className="section-label">
                  YOUR GENERATED ITINERARY
                </span>
                <h2 className="fw-bold mt-2">
                  Explore {itinerary.trip.destination}
                </h2>
                <p className="text-secondary">
                  {itinerary.trip.trip_days} days ·{" "}
                  {itinerary.trip.travelers} travelers
                </p>
              </div>

              <div className="row g-4 mb-4">
                <div className="col-md-6">
                  <div className="p-3 border rounded-3 bg-white h-100">
                    <small className="text-secondary">
                      Total trip budget
                    </small>
                    <h4 className="fw-bold mt-2">
                      ₹{Number(itinerary.trip.budget).toLocaleString("en-IN")}
                    </h4>
                  </div>
                </div>

                <div className="col-md-6">
                  <div className="p-3 border rounded-3 bg-white h-100">
                    <small className="text-secondary">
                      Estimated planned cost
                    </small>
                    <h4 className="fw-bold mt-2">
                      ₹
                      {itinerary.itinerary
                        .reduce(
                          (sum, day) => sum + day.estimated_daily_cost,
                          0
                        )
                        .toLocaleString("en-IN")}
                    </h4>
                  </div>
                </div>
              </div>

              {itinerary.itinerary.map((day) => (
                <div className="planner-card mb-4" key={day.day}>
                  <div className="mb-3">
                    <span className="section-label">
                      DAY {day.day}
                    </span>
                    <h4 className="fw-bold mt-2">
                      {new Date(`${day.date}T12:00:00`).toLocaleDateString(
                        "en-IN",
                        {
                          weekday: "long",
                          day: "numeric",
                          month: "long",
                          year: "numeric",
                        }
                      )}
                    </h4>
                    <span className="badge text-bg-light border p-2">
                      Estimated cost: ₹
                      {day.estimated_daily_cost.toLocaleString("en-IN")}
                    </span>
                  </div>

                  {day.activities.map((activity, index) => (
                    <div
                      className="d-flex gap-3 align-items-start border-top py-3"
                      key={`${day.day}-${index}`}
                    >
                      <strong className="text-primary">
                        {activity.time}
                      </strong>

                      <div className="flex-grow-1">
                        <div className="fw-semibold">
                          {activity.title}
                        </div>
                        <small className="text-secondary">
                          Illustrative activity suggestion
                        </small>
                      </div>

                      <strong>
                        ₹{activity.estimated_cost.toLocaleString("en-IN")}
                      </strong>
                    </div>
                  ))}
                </div>
              ))}

              <div className="alert alert-warning">
                Activities and costs are prototype estimates. Real attraction
                opening hours, travel times and prices are not yet verified.
              </div>
            </div>
          )}

        </section>
      </main>

      <footer className="py-4 border-top bg-white">
        <div className="container d-flex flex-wrap justify-content-between gap-2">
          <span className="fw-bold">✈ TripPilot AI</span>
          <span className="text-secondary small">
            Intelligent planning. Flexible journeys.
          </span>
        </div>
      </footer>
    </div>
  );
}

export default App;
