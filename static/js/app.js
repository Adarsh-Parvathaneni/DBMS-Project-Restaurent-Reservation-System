document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-confirm]").forEach(form => {
    form.addEventListener("submit", event => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  const dateInput = document.getElementById("booking-date");
  const timeInput = document.getElementById("booking-time");
  const guestsInput = document.getElementById("booking-guests");
  const availabilityBox = document.getElementById("availability-box");

  async function checkAvailability() {
    if (!dateInput || !timeInput || !guestsInput || !availabilityBox) return;
    availabilityBox.classList.remove("available", "unavailable");
    availabilityBox.innerHTML = '<span class="availability-dot"></span><span>Checking table availability…</span>';
    try {
      const params = new URLSearchParams({
        date: dateInput.value,
        time: timeInput.value,
        guests: guestsInput.value
      });
      const response = await fetch(`/availability?${params.toString()}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not check availability.");
      if (data.count > 0) {
        availabilityBox.classList.add("available");
        const tables = data.available.map(t => `${t.table_number} (${t.capacity} seats)`).join(", ");
        availabilityBox.innerHTML = `<span class="availability-dot"></span><span><strong>${data.count} suitable table(s) available.</strong><small>${tables}</small></span>`;
      } else {
        availabilityBox.classList.add("unavailable");
        availabilityBox.innerHTML = '<span class="availability-dot"></span><span><strong>No suitable table available.</strong><small>Try a different time or guest count.</small></span>';
      }
    } catch (err) {
      availabilityBox.classList.add("unavailable");
      availabilityBox.innerHTML = `<span class="availability-dot"></span><span>${err.message}</span>`;
    }
  }

  [dateInput, timeInput, guestsInput].forEach(el => {
    if (el) el.addEventListener("change", checkAvailability);
  });
  if (dateInput) checkAvailability();

  document.querySelectorAll(".flash").forEach(el => {
    setTimeout(() => {
      el.classList.add("fade-out");
      setTimeout(() => el.remove(), 400);
    }, 6500);
  });
});
