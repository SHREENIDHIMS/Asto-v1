"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

/**
 * The portal has been replaced by the unified client app at /client.
 * Redirect clients there (the page also guards for non-client identities).
 */
export default function PortalRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/client");
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  );
}
