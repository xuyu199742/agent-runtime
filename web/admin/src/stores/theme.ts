import { ref } from "vue";

export const darkMode = ref(localStorage.getItem("admin_theme") === "dark");
document.documentElement.dataset.theme = darkMode.value ? "dark" : "light";

export function toggleTheme() {
  darkMode.value = !darkMode.value;
  localStorage.setItem("admin_theme", darkMode.value ? "dark" : "light");
  document.documentElement.dataset.theme = darkMode.value ? "dark" : "light";
}
