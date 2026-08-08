"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Building2,
  FileText,
  FolderOpen,
  Home as HomeIcon,
  Loader2,
  LogOut,
  MessageSquare,
  Sparkles,
} from "lucide-react";
import {
  getClientCases,
  getClientDocuments,
  getClientMe,
  getClientProperties,
  getClientDocumentFile,
  openBlobInNewTab,
  ClientCase,
  ClientDocument,
  ClientProfile,
  ClientProperty,
} from "@/lib/api-client";
import { clearToken, decodeToken, getToken } from "@/lib/auth";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { AlertCircle } from "lucide-react";

function formatMoney(value: number | null): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString();
}

export default function PortalPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<ClientProfile | null>(null);
  const [properties, setProperties] = useState<ClientProperty[]>([]);
  const [cases, setCases] = useState<ClientCase[]>([]);
  const [documents, setDocuments] = useState<ClientDocument[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    const claims = token ? decodeToken(token) : null;
    if (!token || claims?.audience !== "client") {
      router.replace("/login");
      return;
    }

    let cancelled = false;
    const load = async () => {
      try {
        const [me, props, casesRes, docsRes] = await Promise.all([
          getClientMe(token),
          getClientProperties(token),
          getClientCases(token),
          getClientDocuments(token),
        ]);
        if (cancelled) return;
        setProfile(me.client);
        setProperties(props.properties);
        setCases(casesRes.cases);
        setDocuments(docsRes.documents);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load portal data");
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [router]);

  const handleLogout = useCallback(() => {
    clearToken();
    router.push("/login");
  }, [router]);

  const handleViewDocument = async (doc: ClientDocument) => {
    try {
      const token = getToken();
      if (!token) return;
      const blob = await getClientDocumentFile(doc.id, token);
      openBlobInNewTab(blob, doc.title || `document-${doc.id}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load document file"
      );
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary text-primary-foreground">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-foreground">Asto</h1>
              <p className="text-xs text-muted-foreground -mt-0.5">Client Portal</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/">
                <MessageSquare className="h-4 w-4 mr-2" />
                Ask Asto
              </Link>
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={handleLogout}>
              <LogOut className="h-4 w-4 mr-2" />
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8 space-y-8">
        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Could not load portal</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {profile && (
          <section>
            <h2 className="text-2xl font-bold mb-1">
              {profile.full_name || profile.email}
            </h2>
            <p className="text-muted-foreground text-sm">{profile.email}</p>
          </section>
        )}

        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <HomeIcon className="w-5 h-5" />
            <h3 className="text-lg font-semibold">My Properties</h3>
          </div>
          {properties.length === 0 ? (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                No properties on file.
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {properties.map((p) => (
                <Card key={p.id}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Building2 className="w-4 h-4 text-muted-foreground" />
                      {p.address}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="text-sm space-y-1">
                    <p className="text-muted-foreground">
                      {p.city}, {p.state} {p.postal_code}
                    </p>
                    <Badge variant="outline">{p.property_type}</Badge>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </section>

        <Separator />

        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <FolderOpen className="w-5 h-5" />
            <h3 className="text-lg font-semibold">My Cases</h3>
          </div>
          {cases.length === 0 ? (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                No cases on file.
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {cases.map((c) => (
                <Card key={c.id}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base flex items-center gap-2">
                      <FolderOpen className="w-4 h-4 text-muted-foreground" />
                      {c.case_number}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="text-sm space-y-2">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Loan amount</span>
                      <span className="font-medium">{formatMoney(c.loan_amount)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Status</span>
                      <Badge variant="outline">{c.status}</Badge>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Opened</span>
                      <span>{formatDate(c.created_at)}</span>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </section>

        <Separator />

        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <FileText className="w-5 h-5" />
            <h3 className="text-lg font-semibold">My Documents</h3>
          </div>
          {documents.length === 0 ? (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                No approved documents available yet.
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="divide-y divide-border">
                {documents.map((d) => (
                  <div key={d.id} className="py-3 flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <p className="font-medium truncate">{d.title}</p>
                      <p className="text-xs text-muted-foreground">
                        {d.doc_type} · {d.department} · v{d.version}
                      </p>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {formatDate(d.created_at)}
                      </span>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => handleViewDocument(d)}
                      >
                        <FileText className="h-3.5 w-3.5 mr-1.5" />
                        View
                      </Button>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </section>
      </main>
    </div>
  );
}
