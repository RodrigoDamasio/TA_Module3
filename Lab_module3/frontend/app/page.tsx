import MigrationApp from "@/components/MigrationApp";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { job } = await searchParams;
  const initialJobId = typeof job === "string" && /^mig_[0-9a-f]+$/.test(job) ? job : null;
  return (
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-8 px-4 py-8 sm:py-12">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Migration Workflow Agent
        </h1>
        <p className="max-w-3xl text-zinc-600 dark:text-zinc-400">
          Four AI agents migrate your code between frameworks — Flask, Express or Django to FastAPI,
          or Python 2 to Python 3. They analyze the project, plan the migration (you can approve
          it), execute the steps, and verify the result. Watch every phase live.
        </p>
      </header>
      <MigrationApp initialJobId={initialJobId} />
    </main>
  );
}
