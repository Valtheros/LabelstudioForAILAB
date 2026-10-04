import { Button } from "@humansignal/ui";
import { Modal } from "../../../components/Modal/Modal";
import { ProjectProvider, useProject } from "../../../providers/ProjectProvider";
import { useFixedLocation } from "../../../providers/RoutesProvider";
import { cn } from "../../../utils/bem";
import { useRefresh } from "../../../utils/hooks";
import { ImportPage } from "./Import";
import { useImportPage } from "./useImportPage";

export const Inner = () => {
  const location = useFixedLocation();
  const refresh = useRefresh();
  const { project } = useProject();
  const { uploading, pageProps } = useImportPage();

  const backToDM = () => {
    if (uploading) return;
    const path = location.pathname.replace(ImportModal.path, "");
    const search = location.search;
    const pathname = `${path}${search !== "?" ? search : ""}`;

    return refresh(pathname);
  };

  return (
    <Modal
      title="Import data"
      onHide={backToDM}
      closeOnClickOutside={false}
      fullscreen
      visible
      bare
    >
      <Modal.Header divided>
        <div className={cn("modal").elem("title").toClassName()}>Import Data</div>

        <Button size="small" onClick={backToDM} waiting={uploading} disabled={uploading} aria-label="Close import">
          Done
        </Button>
      </Modal.Header>
      <ImportPage
        project={project}
        {...pageProps}
      />
    </Modal>
  );
};
export const ImportModal = () => {
  return (
    <ProjectProvider>
      <Inner />
    </ProjectProvider>
  );
};

ImportModal.path = "/import";
ImportModal.modal = true;
