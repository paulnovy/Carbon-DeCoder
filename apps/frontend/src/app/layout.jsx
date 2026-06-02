import "./globals.css";
import { AppSelectionProvider } from "@/components/AppSelectionProvider";
import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";

export const metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_BASE_URL || "http://localhost:3000"),
  title: "Carbon DeCoder",
  description: "Local research-only whole genome sequencing cockpit",
  openGraph: {
    title: "Carbon DeCoder",
    description: "Local research-only whole genome sequencing cockpit",
    images: ["/brand/carbon-decoder-hero.jpg"],
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AppSelectionProvider>
          <Sidebar />
          <TopBar />
          <main
            style={{
              marginLeft: "var(--spacing-sidebar)",
              marginTop: "var(--spacing-topbar)",
              padding: 24,
              minHeight: "calc(100vh - var(--spacing-topbar))",
            }}
          >
            {children}
          </main>
        </AppSelectionProvider>
      </body>
    </html>
  );
}
